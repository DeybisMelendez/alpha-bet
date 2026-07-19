import math
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from forecasts.models import Forecast
from matches.models import Match


# ---------------------------------------------------------------------------
# Utilidades de ponderación temporal.
# docs/xG.md §Ponderación temporal: Peso = exp(-Dias/180).
# ---------------------------------------------------------------------------

def _decay_weight(age_days, decay_days=None):
    if decay_days is None:
        decay_days = settings.FORECAST_DECAY_DAYS
    return math.exp(-max(age_days, 0.0) / decay_days)


def weighted_average(values, dates, ref_date, decay_days=None):
    """Promedio de `values` ponderado por antigüedad respecto a ref_date.

    Cada par (valor, fecha) recibe un peso exp(-(edad_días)/180) según
    docs/xG.md. ref_date es la fecha del partido a pronosticar (o la
    fecha de cálculo si es manual).
    """
    total_w = 0.0
    s = 0.0
    for v, d in zip(values, dates):
        age = max((ref_date - d).total_seconds(), 0.0) / 86400.0
        w = _decay_weight(age, decay_days)
        s += v * w
        total_w += w
    return s / total_w if total_w > 0 else 0.0


# ---------------------------------------------------------------------------
# Elo de equipos en un partido (usado para ajuste por rival).
# ---------------------------------------------------------------------------

def _team_elo_at_match(team, match):
    # Se usa el Elo con el que el equipo entró al partido (elo_before)
    # porque mide su fuerza justo antes de ese resultado. Usar elo_after
    # filtraría el propio resultado en el factor de dificultad del rival.
    if team == match.home_team:
        if match.home_elo_before is not None:
            return match.home_elo_before
        return match.home_team.elo
    if team == match.away_team:
        if match.away_elo_before is not None:
            return match.away_elo_before
        return match.away_team.elo
    return team.elo


def _opponent_elo_at_match(team, match):
    if team == match.home_team:
        if match.away_elo_before is not None:
            return match.away_elo_before
        return match.away_team.elo
    if team == match.away_team:
        if match.home_elo_before is not None:
            return match.home_elo_before
        return match.home_team.elo
    return team.elo


# ---------------------------------------------------------------------------
# Consultas de historial.
# ---------------------------------------------------------------------------

def _finished_qs(team, ref_date=None):
    # ref_date permite acotar el historial a partidos anteriores a una
    # fecha dada. Es esencial para pronósticos retrospectivos (partidos
    # finalizados sin Forecast previo): sin este tope, el motor usaría
    # partidos posteriores al partido a pronosticar y la "predicción"
    # estaría contaminada con información del futuro. Para pronósticos
    # en tiempo real (match still scheduled), ref_date es None y el
    # comportamiento es idéntico al anterior (sin filtro de fecha).
    qs = Match.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        status=Match.Status.FINISHED,
        home_goals__isnull=False,
        away_goals__isnull=False,
        elo_processed=True,
    ).order_by("-utc_date")
    if ref_date is not None:
        qs = qs.filter(utc_date__lte=ref_date)
    return qs


def recent_finished_matches(team, n=None, ref_date=None):
    if n is None:
        n = settings.FORECAST_FORM_LONG
    return _finished_qs(team, ref_date=ref_date)[:n]


def _venue_matches(team, venue, limit, ref_date=None):
    qs = _finished_qs(team, ref_date=ref_date)
    if venue == "home":
        qs = qs.filter(home_team=team)
    elif venue == "away":
        qs = qs.filter(away_team=team)
    return list(qs[:limit]) if limit else list(qs)


def last_match_date(team, ref_date=None):
    """Fecha del partido finalizado más reciente del equipo (o None)."""
    m = _finished_qs(team, ref_date=ref_date).first()
    return m.utc_date if m else None


def is_form_stale(team, max_months=None, now=None, last_date=None, ref_date=None):
    """True si el último partido finalizado del equipo es más antiguo que
    FORECAST_STALE_MONTHS. La forma reciente no es representativa y el
    pronóstico usa fallback Elo-only.

    ref_date se usa como `now` si no se pasa `now` explícito: para
    pronósticos retrospectivos, la antigüedad debe medirse respecto al
    partido a pronosticar, no respecto al momento de cálculo (de lo
    contrario todo partido histórico cumpliría stale=True).
    """
    if max_months is None:
        max_months = getattr(settings, "FORECAST_STALE_MONTHS", 6)
    if now is None:
        now = ref_date if ref_date is not None else timezone.now()
    last = last_date if last_date is not None else last_match_date(
        team, ref_date=ref_date
    )
    if last is None:
        return True
    age_days = (now - last).days
    return age_days > max_months * 30


# ---------------------------------------------------------------------------
# Goles ajustados por dificultad del rival.
# docs/xG.md §Ajuste por dificultad del rival: usar el Elo previo del rival.
# ---------------------------------------------------------------------------

def _goals_for(team, match):
    if team == match.home_team:
        return match.home_goals
    return match.away_goals


def _goals_against(team, match):
    if team == match.home_team:
        return match.away_goals
    return match.home_goals


def adjusted_goals_for(team, match):
    raw = _goals_for(team, match)
    if raw is None:
        return 0.0
    opponent_elo = _opponent_elo_at_match(team, match)
    team_elo = _team_elo_at_match(team, match)
    if team_elo <= 0:
        return float(raw)
    return float(raw) * (opponent_elo / team_elo)


def adjusted_goals_against(team, match):
    # Factor inverso al de ataque: recibir un gol de un rival débil
    # penaliza más la defensa propia (factor = team/opponent).
    raw = _goals_against(team, match)
    if raw is None:
        return 0.0
    opponent_elo = _opponent_elo_at_match(team, match)
    team_elo = _team_elo_at_match(team, match)
    if opponent_elo <= 0:
        return float(raw)
    return float(raw) * (team_elo / opponent_elo)


# ---------------------------------------------------------------------------
# Ratings de ataque/defensa separados por local/visitante.
# docs/xG.md: AtaqueLocal, AtaqueVisitante, DefensaLocal, DefensaVisitante.
# Cada uno es promedio ponderado por antigüedad de goles ajustados por rival.
# ---------------------------------------------------------------------------

def attack_defense_ratings(team, ref_date=None):
    """Devuelve (atk_home, atk_away, def_home, def_away).

    Cada rating combina la producción del equipo en una condición (local
    o visitante) con ponderación temporal exponencial. Si no hay muestra
    suficiente en alguna condición, los ratings devuelven 0.0: el
    llamador gestiona el fallback a Elo-only.

    ref_date acota el historial a partidos anteriores a esa fecha
    (clave para pronósticos retrospectivos). Si es None, no se filtra
    (comportamiento histórico, usado en pronósticos en tiempo real con
    ref_date=now implícito).
    """
    if ref_date is None:
        ref_date = timezone.now()

    venue_limit = settings.FORECAST_FORM_LONG * 2
    home_matches = _venue_matches(team, "home", venue_limit, ref_date=ref_date)
    away_matches = _venue_matches(team, "away", venue_limit, ref_date=ref_date)

    min_venue = settings.FORECAST_MIN_VENUE_HISTORY

    if len(home_matches) >= min_venue:
        atk_home = weighted_average(
            [adjusted_goals_for(team, m) for m in home_matches],
            [m.utc_date for m in home_matches],
            ref_date,
        )
        def_home = weighted_average(
            [adjusted_goals_against(team, m) for m in home_matches],
            [m.utc_date for m in home_matches],
            ref_date,
        )
    else:
        atk_home = def_home = 0.0

    if len(away_matches) >= min_venue:
        atk_away = weighted_average(
            [adjusted_goals_for(team, m) for m in away_matches],
            [m.utc_date for m in away_matches],
            ref_date,
        )
        def_away = weighted_average(
            [adjusted_goals_against(team, m) for m in away_matches],
            [m.utc_date for m in away_matches],
            ref_date,
        )
    else:
        atk_away = def_away = 0.0

    return atk_home, atk_away, def_home, def_away


# ---------------------------------------------------------------------------
# Forma reciente (dos ventanas).
# docs/xG.md: Forma = 0.65·Forma20 + 0.35·Forma5.
# La "forma" se expresa como factor multiplicativo sobre λ, acotado a
# 1 ± FORECAST_FORM_MAX_IMPACT. Se basa en la diferencia entre los
# puntos obtenidos y los puntos esperados por Elo (performance ratio).
# ---------------------------------------------------------------------------

def _expected_points(team, match):
    """Puntos que Elo esperaba del equipo en ese partido (0..3)."""
    home_adv = 0
    if match.competition_id and not match.is_neutral:
        home_adv = match.competition.home_advantage
    team_elo = _team_elo_at_match(team, match)
    opp_elo = _opponent_elo_at_match(team, match)
    is_home = team == match.home_team
    if is_home and not match.is_neutral:
        team_elo += home_adv
    pe = 1 / (1 + 10 ** (-(team_elo - opp_elo) / 400))
    # Puntos esperados: 3·P(win) + 1·P(draw). Aproximación: P(draw)≈0.27.
    return 3 * pe + 1 * 0.27 * (2 * min(pe, 1 - pe))


def _actual_points(team, match):
    gf, ga = _goals_for(team, match), _goals_against(team, match)
    if gf is None or ga is None:
        return 0.0
    if gf > ga:
        return 3.0
    if gf == ga:
        return 1.0
    return 0.0


def recent_form_factor(team, ref_date=None):
    """Factor multiplicativo sobre λ derivado de la forma reciente.

    Compara los puntos reales vs los esperados por Elo en las ventanas
    corta (5) y larga (20) y combina 0.65·Larga + 0.35·Corta. El factor
    se acota a [1 - MAX_IMPACT, 1 + MAX_IMPACT] para que la forma no
    domine el modelo (docs/xG.md: "nunca reemplaza las estadísticas").
    """
    if ref_date is None:
        ref_date = timezone.now()
    impact = settings.FORECAST_FORM_MAX_IMPACT

    def _ratio(matches):
        if not matches:
            return 1.0
        actual = []
        expected = []
        for m in matches:
            actual.append(_actual_points(team, m))
            expected.append(_expected_points(team, m))
        exp_sum = sum(expected) or 1.0
        act_sum = sum(actual)
        ratio = act_sum / exp_sum if exp_sum > 0 else 1.0
        # ratio≈1 → forma esperada. >1 mejor, <1 peor. Clamp al impacto.
        return max(1.0 - impact, min(1.0 + impact, 1.0 + (ratio - 1.0) * impact))

    short_m = list(_finished_qs(team, ref_date=ref_date)[: settings.FORECAST_FORM_SHORT])
    long_m = list(_finished_qs(team, ref_date=ref_date)[: settings.FORECAST_FORM_LONG])
    form_short = _ratio(short_m)
    form_long = _ratio(long_m)
    return (
        settings.FORECAST_FORM_LONG_WEIGHT * form_long
        + settings.FORECAST_FORM_SHORT_WEIGHT * form_short
    )


# ---------------------------------------------------------------------------
# Estimación de goles esperados (λ).
# docs/xG.md: λLocal = √(AtaqueLocal × DefensaVisitante) × FactorElo
# × FactorLocalía × FactorForma. Clamp [0.20, 4.00].
# ---------------------------------------------------------------------------

def _elo_factor(diff):
    """Factor suave (no lineal) por diferencia Elo.

    docs/xG.md: "una función suave que evite exagerar las diferencias".
    Usamos tanh acotada: factor = 1 + gain·tanh(diff/scale).
    """
    gain = settings.FORECAST_ELO_GAIN
    scale = settings.FORECAST_ELO_SCALE
    return 1.0 + gain * math.tanh(diff / scale)


def _clamp_lambda(lam):
    lo = settings.FORECAST_LAMBDA_MIN
    hi = settings.FORECAST_LAMBDA_MAX
    return max(lo, min(hi, lam))


def expected_goals(home, away, home_advantage=None, is_neutral=False,
                   ref_date=None, form_home=None, form_away=None):
    """λ de local y visitante (docs/xG.md y docs/pronostico.md).

    Combina ataque propio × defensa del rival (promedio geométrico),
    factor Elo suave, ventaja de localía y factor de forma reciente.
    Devuelve (xg_home, xg_away) ya clamped [0.20, 4.00].
    """
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    if is_neutral:
        home_advantage = 0
    if ref_date is None:
        ref_date = timezone.now()

    atk_home, atk_away, def_home, def_away = attack_defense_ratings(
        home, ref_date=ref_date
    )
    a_home, a_away, d_home, d_away = attack_defense_ratings(
        away, ref_date=ref_date
    )

    diff = (home.elo + home_advantage) - away.elo
    factor_home = _elo_factor(diff)
    factor_away = _elo_factor(-diff)

    if form_home is None:
        form_home = recent_form_factor(home, ref_date=ref_date)
    if form_away is None:
        form_away = recent_form_factor(away, ref_date=ref_date)

    # Promedio geométrico ataque propio × defensa del rival.
    xg_home = math.sqrt(max(atk_home * d_away, 0.0)) * factor_home * form_home
    xg_away = math.sqrt(max(atk_away * def_home, 0.0)) * factor_away * form_away
    return _clamp_lambda(xg_home), _clamp_lambda(xg_away)


def expected_goals_from_ratings(
    home_elo,
    home_attack,
    home_defense,
    away_elo,
    away_attack,
    away_defense,
    home_advantage=None,
    is_neutral=False,
    form_home=None,
    form_away=None,
):
    """Pronóstico a partir de ratings manuales (sin consultar la DB).

    Útil para cálculos what-if manuales. aquí `home_attack` significa el
    ataque del equipo local jugando como local y `away_defense` la
    defensa del equipo visitante jugando como visitante (análogamente
    para away_attack / home_defense).
    """
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    if is_neutral:
        home_advantage = 0
    diff = (home_elo + home_advantage) - away_elo
    factor_home = _elo_factor(diff)
    factor_away = _elo_factor(-diff)

    if form_home is None:
        form_home = 1.0
    if form_away is None:
        form_away = 1.0

    xg_home = (
        math.sqrt(max(home_attack * away_defense, 0.0))
        * factor_home * form_home
    )
    xg_away = (
        math.sqrt(max(away_attack * home_defense, 0.0))
        * factor_away * form_away
    )
    return _clamp_lambda(xg_home), _clamp_lambda(xg_away)


def expected_goals_elo_only(home, away, home_advantage=None, is_neutral=False,
                            home_elo=None, away_elo=None):
    """Fallback basado solo en diferencia Elo (historial insuficiente).

    Se usa cuando algún equipo no tiene muestra suficiente (<
    FORECAST_MIN_HISTORY). Sin ratings de ataque/defensa, se estima un
    λ baseline (1.35) desplazado por la diferencia Elo de forma suave.

    home_elo/away_elo opcionales permiten inyectar el Elo previo al
    partido (match.home_elo_before) en pronósticos retrospectivos,
    evitando fugas de información del resultado. Si son None, se usa
    el Elo actual de los equipos (comportamiento histórico, para
    pronósticos en tiempo real).
    """
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    if is_neutral:
        home_advantage = 0
    baseline = settings.FORECAST_FALLBACK_BASELINE
    h_elo = home_elo if home_elo is not None else home.elo
    a_elo = away_elo if away_elo is not None else away.elo
    diff = (h_elo + home_advantage) - a_elo

    factor_home = _elo_factor(diff)
    factor_away = _elo_factor(-diff)

    xg_home = _clamp_lambda(baseline * factor_home)
    xg_away = _clamp_lambda(baseline * factor_away)
    return xg_home, xg_away


# ---------------------------------------------------------------------------
# Poisson + Dixon-Coles.
# ---------------------------------------------------------------------------

def poisson_prob(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)


def dixon_coles_tau(i, j, lam_home, lam_away, rho):
    """Factor de corrección Dixon-Coles para celdas de baja anotación.

    Ajusta la dependencia entre goles local/visitante en 0-0, 1-0, 0-1, 1-1.
    rho < 0 incrementa 0-0 y 1-1 (empates) y reduce 1-0 / 0-1, corrigiendo
    la subestimación de empates del Poisson independiente.
    """
    if i == 0 and j == 0:
        return 1 - (lam_home * lam_away * rho)
    if i == 0 and j == 1:
        return 1 + (lam_home * rho)
    if i == 1 and j == 0:
        return 1 + (lam_away * rho)
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def build_matrix(xg_home, xg_away, max_goals=None):
    if max_goals is None:
        max_goals = settings.POISSON_MAX_GOALS
    rho = getattr(settings, "DIXON_COLES_RHO", 0.0)
    home_probs = [poisson_prob(xg_home, k) for k in range(max_goals + 1)]
    away_probs = [poisson_prob(xg_away, k) for k in range(max_goals + 1)]
    matrix = []
    for i in range(max_goals + 1):
        row = []
        for j in range(max_goals + 1):
            p = home_probs[i] * away_probs[j]
            if rho != 0.0:
                p *= dixon_coles_tau(i, j, xg_home, xg_away, rho)
            row.append(p)
        matrix.append(row)
    return matrix


def probabilities_1x2(matrix):
    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    if total > 0:
        p_home /= total
        p_draw /= total
        p_away /= total
    return p_home, p_draw, p_away


def market_probabilities(matrix):
    """Probabilidades de los mercados de apuestas derivados de la matriz.

    Devuelve un dict clave -> probabilidad:
      * 1X2 base: home, draw, away.
      * Doble oportunidad: 1x (local o empate), x2 (empate o visitante).
      * Sin empate (12): gana local o gana visitante = 1 - p_draw.
      * BTTS (ambos marcan): P(local >= 1 y visitante >= 1).
      * Over/Under x.5 para x en {0,1,2,3,4}: prob_over_X5.
      * DNB (Draw No Bet): empate reembolsado → normaliza sobre no-empate.
      * Top correct score (i,j) y su probabilidad.

    Con rho != 0 la matriz no suma exactamente 1, así que todas las
    probabilidades derivadas se normalizan por el total de la matriz.
    """
    max_goals = len(matrix) - 1
    total = sum(p for row in matrix for p in row)
    if total <= 0:
        return {
            "home": 0.0, "draw": 0.0, "away": 0.0,
            "1x": 0.0, "x2": 0.0, "12": 0.0,
            "btts": 0.0, "btts_no": 1.0,
            "score_home": 0.0, "score_home_no": 1.0,
            "score_away": 0.0, "score_away_no": 1.0,
            "over_05": 0.0, "over_15": 0.0, "over_25": 0.0,
            "over_35": 0.0, "over_45": 0.0,
            "dnb_home": 0.5, "dnb_away": 0.5,
        }

    p_home, p_draw, p_away = probabilities_1x2(matrix)

    btts = 0.0
    score_home_zero = 0.0
    score_away_zero = 0.0
    over = {thr: 0.0 for thr in (0, 1, 2, 3, 4)}
    top_i = top_j = 0
    top_p = 0.0
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            if i >= 1 and j >= 1:
                btts += p
            if i == 0:
                score_home_zero += p
            if j == 0:
                score_away_zero += p
            total_goals = i + j
            for thr in over:
                if total_goals > thr:
                    over[thr] += p
            if p > top_p:
                top_p = p
                top_i, top_j = i, j

    btts /= total
    score_home_zero /= total
    score_away_zero /= total
    for thr in over:
        over[thr] /= total

    # DNB: reembolsa empate; reescala a (home, away) sobre no-empate.
    non_draw = p_home + p_away
    dnb_home = p_home / non_draw if non_draw > 0 else 0.5
    dnb_away = p_away / non_draw if non_draw > 0 else 0.5

    return {
        "home": p_home,
        "draw": p_draw,
        "away": p_away,
        "1x": p_home + p_draw,
        "x2": p_draw + p_away,
        "12": p_home + p_away,
        "btts": btts,
        "btts_no": 1.0 - btts,
        "score_home": 1.0 - score_home_zero,
        "score_home_no": score_home_zero,
        "score_away": 1.0 - score_away_zero,
        "score_away_no": score_away_zero,
        "over_05": over[0],
        "over_15": over[1],
        "over_25": over[2],
        "over_35": over[3],
        "over_45": over[4],
        "under_05": 1.0 - over[0],
        "under_15": 1.0 - over[1],
        "under_25": 1.0 - over[2],
        "under_35": 1.0 - over[3],
        "under_45": 1.0 - over[4],
        "dnb_home": dnb_home,
        "dnb_away": dnb_away,
        "top_score": f"{top_i}-{top_j}",
        "top_score_prob": top_p / total,
    }


def top_correct_scores(matrix, n=5):
    """Top n marcadores exactos más probables de la matriz Poisson.

    Devuelve una lista de dicts ``{"score": "i-j", "prob": float}``
    ordenada de mayor a menor probabilidad, con la probabilidad
    normalizada por el total de la matriz (para respetar la corrección
    Dixon-Coles cuando rho != 0). Se usa para mostrar el top 5 de
    resultados más probables en las vistas de pronóstico.
    """
    total = sum(p for row in matrix for p in row)
    if total <= 0:
        return []
    scores = []
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            scores.append((i, j, p))
    scores.sort(key=lambda item: item[2], reverse=True)
    return [
        {"score": f"{i}-{j}", "prob": p / total}
        for i, j, p in scores[:n]
    ]


def _form_summary(team):
    matches = list(recent_finished_matches(team, n=settings.FORECAST_FORM_LONG))
    form = []
    for m in matches:
        form.append({
            "date": m.utc_date.date().isoformat(),
            "opponent": (
                m.away_team.name if team == m.home_team else m.home_team.name
            ),
            "goals_for": _goals_for(team, m),
            "goals_against": _goals_against(team, m),
            "adjusted_for": round(adjusted_goals_for(team, m), 3),
            "adjusted_against": round(adjusted_goals_against(team, m), 3),
        })
    atk_home, atk_away, def_home, def_away = attack_defense_ratings(team)
    return {
        "matches": form,
        "attack_home": round(atk_home, 3),
        "attack_away": round(atk_away, 3),
        "defense_home": round(def_home, 3),
        "defense_away": round(def_away, 3),
    }


def team_history_count(team, ref_date=None):
    # Solo se cuentan partidos con Elo procesado: la forma reciente usa
    # elo_before para ajustar goles por dificultad del rival, por lo que
    # los partidos sin procesar no son utilizables por el modelo completo.
    return _finished_qs(team, ref_date=ref_date).count()


def _has_venue_history(team, ref_date=None):
    """Comprueba si el equipo tiene historial suficiente por condición."""
    min_venue = settings.FORECAST_MIN_VENUE_HISTORY
    home_ok = _venue_matches(team, "home", min_venue, ref_date=ref_date)
    away_ok = _venue_matches(team, "away", min_venue, ref_date=ref_date)
    return len(home_ok) >= min_venue and len(away_ok) >= min_venue


# ---------------------------------------------------------------------------
# Caché de forma por equipo (corrida batch) y generación de pronósticos.
# ---------------------------------------------------------------------------

def _team_form_data(team, cache=None, ref_date=None):
    """Calcula y cachea todos los datos de forma de un equipo.

    Durante una corrida batch (generate_for_scheduled_matches,
    regenerate_for_teams) se reutiliza el mismo cache dict para evitar
    reconsultar la forma de equipos que aparecen en varios partidos.

    Devuelve un dict con: history_count, last_date, stale, has_venue,
    attack_home/away, defense_home/away, form_factor, form_summary.
    """
    if cache is not None and team.id in cache:
        return cache[team.id]

    if ref_date is None:
        ref_date = timezone.now()

    history_count = team_history_count(team, ref_date=ref_date)
    last_date = last_match_date(team, ref_date=ref_date)
    stale = is_form_stale(team, last_date=last_date, ref_date=ref_date)
    has_venue = _has_venue_history(team, ref_date=ref_date)
    atk_home, atk_away, def_home, def_away = attack_defense_ratings(
        team, ref_date=ref_date
    )
    form_factor = recent_form_factor(team, ref_date=ref_date)
    form_summary = _form_summary(team)

    data = {
        "history_count": history_count,
        "last_date": last_date,
        "stale": stale,
        "has_venue": has_venue,
        "attack_home": atk_home,
        "attack_away": atk_away,
        "defense_home": def_home,
        "defense_away": def_away,
        "form_factor": form_factor,
        "form_summary": form_summary,
    }
    if cache is not None:
        cache[team.id] = data
    return data


def _home_advantage_for(match):
    comp = match.competition
    if comp is None or match.is_neutral:
        return 0 if match.is_neutral else settings.ELO_HOME_ADVANTAGE
    return comp.home_advantage


def _elo_to_use(team, match):
    """Elo con el que el equipo entró al partido, si existe snapshot.

    Para pronósticos en tiempo real (match SCHEDULED) no hay
    home_elo_before/away_elo_before todavía, así que se usa el Elo
    actual (team.elo). Para pronósticos retrospectivos (match ya
    finalizado y con Elo procesado) los snapshots existen y reflejan
    la fuerza justo antes del partido: usarlos evita fugas de
    información del resultado del propio partido.
    """
    if team == match.home_team and match.home_elo_before is not None:
        return match.home_elo_before
    if team == match.away_team and match.away_elo_before is not None:
        return match.away_elo_before
    return team.elo


def _has_pending_prior_match(team, ref_match):
    """True si `team` tiene un partido programado previo a `ref_match`.

    Se considera "previo pendiente" a cualquier Match SCHEDULED/TIMED
    futuro (utc_date >= now) con utc_date < ref_match.utc_date en el que
    el equipo participe. Es la condición que hace que el pronóstico de
    ref_match pueda cambiar al finalizar ese partido anterior (el flujo
    `apply_elo_update` -> `regenerate_for_teams` ya lo actualiza).

    No consume API: es una query local con `exists()`.
    """
    now = timezone.now()
    return Match.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
        utc_date__gte=now,
        utc_date__lt=ref_match.utc_date,
    ).exists()


def generate_forecast(match, cache=None):
    home = match.home_team
    away = match.away_team

    home_data = _team_form_data(home, cache=cache, ref_date=match.utc_date)
    away_data = _team_form_data(away, cache=cache, ref_date=match.utc_date)

    min_history = settings.FORECAST_MIN_HISTORY
    home_stale = home_data["stale"]
    away_stale = away_data["stale"]

    # Fallback si algún equipo sin historial suficiente, sin muestra por
    # condición, o forma desactualizada (huecos por plan Free de la API).
    is_fallback = (
        home_data["history_count"] < min_history
        or away_data["history_count"] < min_history
        or not home_data["has_venue"]
        or not away_data["has_venue"]
        or home_stale
        or away_stale
    )

    home_adv = _home_advantage_for(match)

    # Elo con el que cada equipo entró al partido. Para partidos ya
    # finalizados con Elo procesado, los snapshots *_elo_before existen
    # y deben usarse para evitar fugas de información (docs/xG.md §Ajuste
    # por dificultad del rival: "utilizar el Elo previo del rival"). Para
    # partidos programados los snapshots son None y se usa team.elo.
    home_elo = _elo_to_use(home, match)
    away_elo = _elo_to_use(away, match)

    if is_fallback:
        xg_home, xg_away = expected_goals_elo_only(
            home, away,
            home_advantage=home_adv,
            is_neutral=match.is_neutral,
            home_elo=home_elo,
            away_elo=away_elo,
        )
        form_home = {
            "history_count": home_data["history_count"],
            "stale": home_stale,
            "has_venue": home_data["has_venue"],
        }
        form_away = {
            "history_count": away_data["history_count"],
            "stale": away_stale,
            "has_venue": away_data["has_venue"],
        }
    else:
        xg_home, xg_away = expected_goals_from_ratings(
            home_elo,
            home_data["attack_home"],
            home_data["defense_home"],
            away_elo,
            away_data["attack_away"],
            away_data["defense_away"],
            home_advantage=home_adv,
            is_neutral=match.is_neutral,
            form_home=home_data["form_factor"],
            form_away=away_data["form_factor"],
        )
        form_home = home_data["form_summary"]
        form_home["form_factor"] = round(home_data["form_factor"], 3)
        form_away = away_data["form_summary"]
        form_away["form_factor"] = round(away_data["form_factor"], 3)

    matrix = build_matrix(xg_home, xg_away)
    p_home, p_draw, p_away = probabilities_1x2(matrix)
    markets = market_probabilities(matrix)

    pending_prior = (
        _has_pending_prior_match(home, match)
        or _has_pending_prior_match(away, match)
    )

    forecast, _ = Forecast.objects.update_or_create(
        match=match,
        defaults={
            "xg_home": xg_home,
            "xg_away": xg_away,
            "prob_home_win": p_home,
            "prob_draw": p_draw,
            "prob_away_win": p_away,
            "prob_over_05": markets["over_05"],
            "prob_over_15": markets["over_15"],
            "prob_over_25": markets["over_25"],
            "prob_over_35": markets["over_35"],
            "prob_over_45": markets["over_45"],
            "prob_btts": markets["btts"],
            "prob_btts_no": markets["btts_no"],
            "prob_score_home": markets["score_home"],
            "prob_score_home_no": markets["score_home_no"],
            "prob_score_away": markets["score_away"],
            "prob_score_away_no": markets["score_away_no"],
            "prob_1x": markets["1x"],
            "prob_x2": markets["x2"],
            "prob_12": markets["12"],
            "prob_dnb_home": markets["dnb_home"],
            "prob_dnb_away": markets["dnb_away"],
            "top_score": markets["top_score"],
            "top_score_prob": markets["top_score_prob"],
            "form_home": form_home,
            "form_away": form_away,
            "is_fallback": is_fallback,
            "pending_prior_match": pending_prior,
        },
    )

    return forecast


def scheduled_matches_in_window(days=None):
    """Partidos programados dentro de la ventana hacia adelante.

    Solo se pronostican partidos cercanos (pronóstico semanal) porque los
    datos lejanos (fechas, forma reciente, Elo) cambian con el tiempo.
    """
    if days is None:
        days = settings.FORECAST_SCHEDULE_DAYS
    now = timezone.now()
    horizon = now + timedelta(days=days)
    return Match.objects.filter(
        status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
        utc_date__gte=now,
        utc_date__lte=horizon,
    ).order_by("utc_date")


def generate_for_scheduled_matches(limit=None, days=None):
    """Genera pronósticos para partidos programados en la ventana semanal.

    Devuelve (generated, fallback) donde fallback es el número de
    pronósticos calculados solo con Elo por historial insuficiente.

    Usa un cache de forma reciente por equipo para evitar reconsultar
    equipos que aparecen en varios partidos de la misma ventana.
    """
    scheduled = scheduled_matches_in_window(days=days)
    if limit:
        scheduled = scheduled[:limit]
    # Precargar relaciones para evitar N+1 en el iter.
    scheduled = scheduled.select_related("home_team", "away_team", "competition")
    cache = {}
    generated = 0
    fallback = 0
    for match in scheduled:
        try:
            forecast = generate_forecast(match, cache=cache)
            if forecast is not None:
                generated += 1
                if forecast.is_fallback:
                    fallback += 1
        except Exception:
            import logging
            logging.getLogger("alpha").exception(
                "Error generando pronóstico para partido %s", match.id_api
            )
    return generated, fallback


def upcoming_matches_for_team(team, days=None):
    """Próximos partidos programados de un equipo dentro de la ventana."""
    if days is None:
        days = settings.FORECAST_SCHEDULE_DAYS
    now = timezone.now()
    horizon = now + timedelta(days=days)
    return Match.objects.filter(
        Q(home_team=team) | Q(away_team=team),
        status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
        utc_date__gte=now,
        utc_date__lte=horizon,
    ).select_related("home_team", "away_team", "competition").order_by("utc_date")


def regenerate_upcoming_forecasts(team, days=None):
    """Regenera los pronósticos de los próximos partidos de un equipo.

    Se invoca tras actualizar el Elo del equipo (al finalizar un partido)
    para que los pronósticos de los partidos siguientes reflejen el nuevo
    Elo y la nueva forma reciente.
    """
    matches = upcoming_matches_for_team(team, days=days)
    cache = {}
    regenerated = 0
    fallback = 0
    for match in matches:
        try:
            forecast = generate_forecast(match, cache=cache)
            if forecast is not None:
                regenerated += 1
                if forecast.is_fallback:
                    fallback += 1
        except Exception:
            import logging
            logging.getLogger("alpha").exception(
                "Error regenerando pronóstico para partido %s", match.id_api
            )
    return regenerated, fallback


def regenerate_for_teams(teams, days=None):
    """Regenera pronósticos de los próximos partidos de varios equipos.

    Evita procesar dos veces el mismo partido cuando ambos equipos están en
    la lista (caso habitual: home y away del partido recién finalizado).

    Usa un cache de forma reciente compartido: tras un update de Elo, la
    forma de los equipos cambia y se recalcula para todos a la vez.
    """
    seen = set()
    cache = {}
    generated = 0
    fallback = 0
    for team in teams:
        for match in upcoming_matches_for_team(team, days=days):
            if match.pk in seen:
                continue
            seen.add(match.pk)
            try:
                forecast = generate_forecast(match, cache=cache)
                if forecast is not None:
                    generated += 1
                    if forecast.is_fallback:
                        fallback += 1
            except Exception:
                import logging
                logging.getLogger("alpha").exception(
                    "Error regenerando pronóstico para partido %s",
                    match.id_api,
                )
    return generated, fallback
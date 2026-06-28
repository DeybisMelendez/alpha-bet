import math
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from forecasts.models import Forecast
from matches.models import Match


def _team_elo_at_match(team, match):
    # Se usa el Elo con el que el equipo entró al partido (elo_before) porque
    # mide su fuerza justo antes de ese resultado. Usar elo_after filtraría
    # el propio resultado en el factor de dificultad del rival.
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


def recent_finished_matches(team, n=None):
    if n is None:
        n = settings.FORECAST_FORM_MATCHES
    return (
        Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            status=Match.Status.FINISHED,
            home_goals__isnull=False,
            away_goals__isnull=False,
            elo_processed=True,
        )
        .order_by("-utc_date")[:n]
    )


def last_match_date(team):
    """Fecha del partido finalizado más reciente del equipo (o None)."""
    m = (
        Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            status=Match.Status.FINISHED,
            home_goals__isnull=False,
            away_goals__isnull=False,
            elo_processed=True,
        )
        .order_by("-utc_date")
        .first()
    )
    return m.utc_date if m else None


def is_form_stale(team, max_months=None, now=None, last_date=None):
    """Detecta si la forma reciente del equipo está desactualizada.

    Devuelve True si el último partido finalizado del equipo es más
    antiguo que FORECAST_STALE_MONTHS. En ese caso la forma reciente no
    es representativa y el pronóstico debe usar fallback Elo-only.

    last_date permite inyectar la fecha precalculada para evitar una
    query duplicada cuando el llamador ya la obtuvo.
    """
    if max_months is None:
        max_months = getattr(settings, "FORECAST_STALE_MONTHS", 6)
    if now is None:
        now = timezone.now()
    last = last_date if last_date is not None else last_match_date(team)
    if last is None:
        return True
    age_days = (now - last).days
    return age_days > max_months * 30


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
    factor = opponent_elo / team_elo
    return raw * factor


def adjusted_goals_against(team, match):
    # Factor inverso al de ataque: recibir un gol de un rival débil penaliza
    # más la defensa propia, mientras que recibirlo de un rival fuerte es más
    # esperado y se atenúa. Por eso aquí el factor es team/opponent (inverso
    # del de adjusted_goals_for, que usa opponent/team).
    raw = _goals_against(team, match)
    if raw is None:
        return 0.0
    opponent_elo = _opponent_elo_at_match(team, match)
    team_elo = _team_elo_at_match(team, match)
    if opponent_elo <= 0:
        return float(raw)
    factor = team_elo / opponent_elo
    return raw * factor


def attack_defense_ratings(team, n=None):
    matches = recent_finished_matches(team, n=n)
    if not matches:
        return 0.0, 0.0
    attack_values = [adjusted_goals_for(team, m) for m in matches]
    defense_values = [adjusted_goals_against(team, m) for m in matches]
    attack = sum(attack_values) / len(attack_values)
    defense = sum(defense_values) / len(defense_values)
    return attack, defense


def expected_goals(home, away, home_advantage=None):
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    home_elo = home.elo + home_advantage
    away_elo = away.elo
    diff = home_elo - away_elo

    atk_home, def_home = attack_defense_ratings(home)
    atk_away, def_away = attack_defense_ratings(away)

    factor_home = 1 + (diff / 1000)
    factor_away = 1 - (diff / 1000)

    # Goles esperados combinando el ataque propio con la defensa del rival.
    # Se usa promedio geométrico sqrt(atk * def) en lugar del aritmético
    # porque el modelo Poisson subyacente (Dixon-Coles) es multiplicativo:
    # log(λ) = μ + α_ataque + β_defensa. El promedio geométrico respeta esa
    # estructura y evita el amortiguamiento del aritmético (ataque fuerte vs
    # defensa fuerte ya no colapsan al centro).
    xg_home = math.sqrt(max(atk_home * def_away, 0.0)) * factor_home
    xg_away = math.sqrt(max(atk_away * def_home, 0.0)) * factor_away

    xg_home = max(xg_home, 0.0)
    xg_away = max(xg_away, 0.0)
    return xg_home, xg_away


def expected_goals_from_ratings(
    home_elo,
    home_attack,
    home_defense,
    away_elo,
    away_attack,
    away_defense,
    home_advantage=None,
):
    """Pronóstico a partir de ratings manuales (sin consultar la DB).

    Replica la lógica de `expected_goals` pero recibiendo los valores
    numéricos directamente. Útil para cálculos what-if manuales donde no
    existe un Match o Team persistido.
    """
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    home_elo_adj = home_elo + home_advantage
    away_elo_adj = away_elo
    diff = home_elo_adj - away_elo_adj

    factor_home = 1 + (diff / 1000)
    factor_away = 1 - (diff / 1000)

    xg_home = math.sqrt(max(home_attack * away_defense, 0.0)) * factor_home
    xg_away = math.sqrt(max(away_attack * home_defense, 0.0)) * factor_away

    xg_home = max(xg_home, 0.0)
    xg_away = max(xg_away, 0.0)
    return xg_home, xg_away


def expected_goals_elo_only(home, away, home_advantage=None):
    """Pronóstico fallback basado solo en la diferencia Elo.

    Se usa cuando alguno de los dos equipos no tiene historial suficiente
    (< FORECAST_MIN_HISTORY). En lugar de omitir el pronóstico, se estima
    los goles esperados usando un baseline de goles por partido ajustado
    por la diferencia Elo. A medida que los equipos acumulen historial,
    el modelo completo (Poisson + forma reciente) sustituye este fallback.
    """
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    baseline = settings.FORECAST_FALLBACK_BASELINE
    home_elo = home.elo + home_advantage
    away_elo = away.elo
    diff = home_elo - away_elo

    factor_home = 1 + (diff / 1000)
    factor_away = 1 - (diff / 1000)

    xg_home = max(baseline * factor_home, 0.0)
    xg_away = max(baseline * factor_away, 0.0)
    return xg_home, xg_away


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


# Mercados derivados mostrables en la vista de pronóstico. El orden define
# cómo se presentan en la UI. Las claves coinciden con los campos de cuotas
# del ValueBetForm (odd_<clave>) y con los labels esperados por el template.
MARKET_LABELS = (
    ("home", "Local (1)"),
    ("draw", "Empate (X)"),
    ("away", "Visitante (2)"),
    ("1x", "Doble op. 1X"),
    ("x2", "Doble op. X2"),
    ("12", "Sin empate (12)"),
    ("btts", "Ambos marcan"),
)


def market_probabilities(matrix):
    """Probabilidades de todos los mercados de apuestas derivados de la matriz.

    Devuelve un dict clave -> probabilidad:
      * 1X2 base: home, draw, away.
      * Doble oportunidad: 1x (local o empate), x2 (empate o visitante).
      * Sin empate (12): gana local o gana visitante = 1 - p_draw.
      * BTTS (ambos marcan): P(local >= 1 y visitante >= 1).

    El BTTS se suma celda a celda (no se asume independencia entre goles)
    porque la corrección Dixon-Coles introduce dependencia en baja anotación.

    Con rho != 0 la matriz no suma exactamente 1, así que todas las
    probabilidades derivadas se normalizan por el total de la matriz para
    mantener consistencia con probabilities_1x2 (que también normaliza).
    """
    total = sum(p for row in matrix for p in row)
    if total <= 0:
        return {
            "home": 0.0, "draw": 0.0, "away": 0.0,
            "1x": 0.0, "x2": 0.0, "12": 0.0,
            "btts": 0.0, "btts_no": 1.0,
        }

    p_home, p_draw, p_away = probabilities_1x2(matrix)
    btts = 0.0
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            if i >= 1 and j >= 1:
                btts += p
    btts = btts / total
    return {
        "home": p_home,
        "draw": p_draw,
        "away": p_away,
        "1x": p_home + p_draw,
        "x2": p_draw + p_away,
        "12": p_home + p_away,
        "btts": btts,
        "btts_no": 1.0 - btts,
    }


def _form_summary(team):
    matches = recent_finished_matches(team)
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
    atk, deff = attack_defense_ratings(team)
    return {
        "matches": form,
        "attack_rating": round(atk, 3),
        "defense_rating": round(deff, 3),
    }


def team_history_count(team):
    # Solo se cuentan partidos con Elo procesado: la forma reciente usa
    # elo_before para ajustar goles por dificultad del rival, por lo que
    # los partidos sin procesar no son utilizables por el modelo completo.
    return (
        Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            status=Match.Status.FINISHED,
            home_goals__isnull=False,
            away_goals__isnull=False,
            elo_processed=True,
        ).count()
    )


def value_bet_analysis(market_probs, odds):
    """Compara las probabilidades del modelo con cuotas por mercado.

    Recibe las probabilidades de los mercados (dict clave -> prob, ver
    `market_probabilities`) y las cuotas ingresadas (dict clave -> odd,
    pueden ser None para los mercados sin cuota).

    Para cada mercado con cuota calcula:
      * fair_odds: cuota justa del modelo (1 / prob_modelo).
      * implied_prob: probabilidad implícita en la cuota (1 / cuota).
      * ev: valor esperado por unidad apostada (prob_modelo * cuota - 1).
            ev > 0 indica value bet.
      * edge: ventaja del modelo sobre la cuota (prob_modelo - implied_prob).
      * is_value: True si ev > 0.

    El margen de la casa (vig/overround) solo tiene sentido sobre un grupo
    de resultados mutuamente excluyentes y exhaustivos, por eso se calcula
    únicamente para el trío 1X2 (cuando las tres cuotas están presentes).

    La recomendación es el mercado con mayor EV positivo.

    Las cuotas se ingresan manualmente: ninguna API del proyecto ofrece
    odds en su plan Free. El análisis es transitorio (no se persiste).
    """
    rows = []
    for key, _label in MARKET_LABELS:
        prob = market_probs.get(key)
        odd = odds.get(key)
        if prob is None:
            continue
        if odd is None or odd <= 0:
            rows.append({"label": key, "prob": prob, "odd": None})
            continue
        fair_odds = 1.0 / prob if prob > 0 else float("inf")
        implied = 1.0 / odd
        ev = prob * odd - 1.0
        edge = prob - implied
        rows.append({
            "label": key,
            "prob": prob,
            "odd": odd,
            "implied_prob": implied,
            "fair_odds": fair_odds,
            "ev": ev,
            "edge": edge,
            "is_value": ev > 0,
        })

    provided = [r for r in rows if r["odd"] is not None]

    # Vig solo para el trío 1X2: resultados que particionan el espacio.
    trio = [r for r in rows if r["label"] in ("home", "draw", "away") and r["odd"] is not None]
    vig = sum(r["implied_prob"] for r in trio) - 1.0 if len(trio) == 3 else None

    value_rows = [r for r in provided if r["is_value"]]
    recommendation = max(value_rows, key=lambda r: r["ev"]) if value_rows else None

    return {"rows": rows, "vig": vig, "recommendation": recommendation}


def _team_form_data(team, cache=None):
    """Calcula y cachea todos los datos de forma de un equipo.

    Durante una corrida batch (generate_for_scheduled_matches,
    regenerate_for_teams) se reutiliza el mismo cache dict para evitar
    reconsultar la forma de equipos que aparecen en varios partidos.

    Devuelve un dict con: history_count, last_date, stale, attack,
    defense, form_summary.
    """
    if cache is not None and team.id in cache:
        return cache[team.id]

    history_count = team_history_count(team)
    last_date = last_match_date(team)
    stale = is_form_stale(team, last_date=last_date)
    attack, defense = attack_defense_ratings(team)
    form_summary = _form_summary(team)

    data = {
        "history_count": history_count,
        "last_date": last_date,
        "stale": stale,
        "attack": attack,
        "defense": defense,
        "form_summary": form_summary,
    }
    if cache is not None:
        cache[team.id] = data
    return data


def generate_forecast(match, cache=None):
    home = match.home_team
    away = match.away_team

    # El cache evita reconsultar la forma de equipos que aparecen en
    # varios partidos dentro de la misma corrida batch.
    home_data = _team_form_data(home, cache=cache)
    away_data = _team_form_data(away, cache=cache)

    home_history = home_data["history_count"]
    away_history = away_data["history_count"]
    min_history = settings.FORECAST_MIN_HISTORY

    # Se usa fallback cuando un equipo no tiene historial suficiente o
    # cuando su forma reciente está desactualizada (stale). Esto último
    # ocurre con selecciones nacionales cuyo historial tiene huecos por
    # las restricciones del plan Free de API-Football (solo hoy ± 1 día).
    home_stale = home_data["stale"]
    away_stale = away_data["stale"]

    is_fallback = (
        home_history < min_history
        or away_history < min_history
        or home_stale
        or away_stale
    )

    if is_fallback:
        xg_home, xg_away = expected_goals_elo_only(home, away)
        form_home = {
            "history_count": home_history,
            "stale": home_stale,
        }
        form_away = {
            "history_count": away_history,
            "stale": away_stale,
        }
    else:
        # Pronóstico completo usando los ratings cacheados de forma reciente.
        xg_home, xg_away = expected_goals_from_ratings(
            home.elo,
            home_data["attack"],
            home_data["defense"],
            away.elo,
            away_data["attack"],
            away_data["defense"],
        )
        form_home = home_data["form_summary"]
        form_away = away_data["form_summary"]

    matrix = build_matrix(xg_home, xg_away)
    p_home, p_draw, p_away = probabilities_1x2(matrix)

    forecast, _ = Forecast.objects.update_or_create(
        match=match,
        defaults={
            "xg_home": xg_home,
            "xg_away": xg_away,
            "prob_home_win": p_home,
            "prob_draw": p_draw,
            "prob_away_win": p_away,
            "form_home": form_home,
            "form_away": form_away,
            "is_fallback": is_fallback,
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

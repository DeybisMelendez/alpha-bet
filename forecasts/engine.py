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
        )
        .order_by("-utc_date")[:n]
    )


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
    raw = _goals_against(team, match)
    if raw is None:
        return 0.0
    opponent_elo = _opponent_elo_at_match(team, match)
    team_elo = _team_elo_at_match(team, match)
    if team_elo <= 0:
        return float(raw)
    factor = opponent_elo / team_elo
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
    # Se promedian ambos ratings para evitar sobreestimar cuando solo uno
    # es alto (ataque fuerte vs defensa fuerte deben atenuarse, no tomar el
    # mayor). Coherente con Poisson bivariado estándar (Dixon-Coles).
    xg_home = (atk_home + def_away) / 2 * factor_home
    xg_away = (atk_away + def_home) / 2 * factor_away

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

    xg_home = (home_attack + away_defense) / 2 * factor_home
    xg_away = (away_attack + home_defense) / 2 * factor_away

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
    return (
        Match.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            status=Match.Status.FINISHED,
            home_goals__isnull=False,
            away_goals__isnull=False,
        ).count()
    )


def value_bet_analysis(prob_home, prob_draw, prob_away, odd_home, odd_draw, odd_away):
    """Compara las probabilidades del modelo con cuotas de casa de apuestas.

    Para cada resultado (1, X, 2) calcula:
      * fair_odds: cuota justa del modelo (1 / prob_modelo).
      * implied_prob: probabilidad implícita en la cuota (1 / cuota).
      * ev: valor esperado por unidad apostada (prob_modelo * cuota - 1).
            ev > 0 indica value bet.
      * edge: ventaja del modelo sobre la cuota (prob_modelo - implied_prob).
      * is_value: True si ev > 0.

    Además calcula el margen de la casa (vig/overround) como la suma de las
    probabilidades implícitas menos 1, y la recomendación (resultado con
    mayor EV positivo).

    Las cuotas se ingresan manualmente: ninguna API del proyecto ofrece
    odds en su plan Free. El análisis es transitorio (no se persiste).
    """
    rows = []
    labels = ["home", "draw", "away"]
    probs = [prob_home, prob_draw, prob_away]
    odds = [odd_home, odd_draw, odd_away]

    for label, prob, odd in zip(labels, probs, odds):
        if odd is None or odd <= 0:
            rows.append({"label": label, "odd": None})
            continue
        fair_odds = 1.0 / prob if prob > 0 else float("inf")
        implied = 1.0 / odd
        ev = prob * odd - 1.0
        edge = prob - implied
        rows.append({
            "label": label,
            "odd": odd,
            "prob": prob,
            "implied_prob": implied,
            "fair_odds": fair_odds,
            "ev": ev,
            "edge": edge,
            "is_value": ev > 0,
        })

    provided = [r for r in rows if r["odd"] is not None]
    vig = None
    if len(provided) == 3:
        vig = sum(r["implied_prob"] for r in provided) - 1.0

    value_rows = [r for r in provided if r["is_value"]]
    recommendation = max(value_rows, key=lambda r: r["ev"]) if value_rows else None

    return {"rows": rows, "vig": vig, "recommendation": recommendation}


def generate_forecast(match):
    home = match.home_team
    away = match.away_team

    home_history = team_history_count(home)
    away_history = team_history_count(away)
    min_history = settings.FORECAST_MIN_HISTORY

    is_fallback = (
        home_history < min_history or away_history < min_history
    )

    if is_fallback:
        xg_home, xg_away = expected_goals_elo_only(home, away)
        form_home = {"history_count": home_history}
        form_away = {"history_count": away_history}
    else:
        xg_home, xg_away = expected_goals(home, away)
        form_home = _form_summary(home)
        form_away = _form_summary(away)

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
    """
    scheduled = scheduled_matches_in_window(days=days)
    if limit:
        scheduled = scheduled[:limit]
    generated = 0
    fallback = 0
    for match in scheduled:
        try:
            forecast = generate_forecast(match)
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
    ).order_by("utc_date")


def regenerate_upcoming_forecasts(team, days=None):
    """Regenera los pronósticos de los próximos partidos de un equipo.

    Se invoca tras actualizar el Elo del equipo (al finalizar un partido)
    para que los pronósticos de los partidos siguientes reflejen el nuevo
    Elo y la nueva forma reciente.
    """
    matches = upcoming_matches_for_team(team, days=days)
    regenerated = 0
    fallback = 0
    for match in matches:
        try:
            forecast = generate_forecast(match)
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
    """
    seen = set()
    generated = 0
    fallback = 0
    for team in teams:
        for match in upcoming_matches_for_team(team, days=days):
            if match.pk in seen:
                continue
            seen.add(match.pk)
            try:
                forecast = generate_forecast(match)
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

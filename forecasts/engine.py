import math

from django.conf import settings
from django.db.models import Q

from forecasts.models import Forecast
from matches.models import Match


def _team_elo_at_match(team, match):
    if match.elo_processed and team == match.home_team:
        return match.home_elo_after
    if match.elo_processed and team == match.away_team:
        return match.away_elo_after
    return team.elo


def _opponent_elo_at_match(team, match):
    if team == match.home_team:
        if match.away_elo_after is not None:
            return match.away_elo_after
        return match.away_team.elo
    if match.home_elo_after is not None:
        return match.home_elo_after
    return match.home_team.elo


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
    team_elo = team.elo
    if team_elo <= 0:
        return float(raw)
    factor = opponent_elo / team_elo
    return raw * factor


def adjusted_goals_against(team, match):
    raw = _goals_against(team, match)
    if raw is None:
        return 0.0
    opponent_elo = _opponent_elo_at_match(team, match)
    team_elo = team.elo
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

    xg_home = max(atk_home, def_away) * factor_home
    xg_away = max(atk_away, def_home) * factor_away

    xg_home = max(xg_home, 0.0)
    xg_away = max(xg_away, 0.0)
    return xg_home, xg_away


def poisson_prob(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)


def build_matrix(xg_home, xg_away, max_goals=None):
    if max_goals is None:
        max_goals = settings.POISSON_MAX_GOALS
    home_probs = [poisson_prob(xg_home, k) for k in range(max_goals + 1)]
    away_probs = [poisson_prob(xg_away, k) for k in range(max_goals + 1)]
    matrix = []
    for i in range(max_goals + 1):
        row = []
        for j in range(max_goals + 1):
            row.append(home_probs[i] * away_probs[j])
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


def generate_forecast(match):
    home = match.home_team
    away = match.away_team

    if team_history_count(home) < settings.FORECAST_MIN_HISTORY:
        return None
    if team_history_count(away) < settings.FORECAST_MIN_HISTORY:
        return None

    xg_home, xg_away = expected_goals(home, away)
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
            "form_home": _form_summary(home),
            "form_away": _form_summary(away),
        },
    )
    return forecast


def generate_for_scheduled_matches(limit=None):
    scheduled = Match.objects.filter(
        status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
    ).order_by("utc_date")
    if limit:
        scheduled = scheduled[:limit]
    generated = 0
    skipped = 0
    for match in scheduled:
        try:
            forecast = generate_forecast(match)
            if forecast is not None:
                generated += 1
            else:
                skipped += 1
        except Exception:
            import logging
            logging.getLogger("alpha").exception(
                "Error generando pronóstico para partido %s", match.id_api
            )
    return generated, skipped

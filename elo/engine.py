import math

from django.conf import settings

from elo.models import EloLog
from matches.models import Match


def expected_probability(elo_a, elo_b, home_advantage=None, is_home=True):
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    effective_a = elo_a + (home_advantage if is_home else 0)
    diff = effective_a - elo_b
    e_a = 1 / (1 + 10 ** (-diff / 400))
    return e_a, 1 - e_a


def goal_multiplier(goal_diff):
    if goal_diff <= 0:
        return 0.0
    return math.log(goal_diff + 1)


def strength_multiplier(goal_diff, delta_elo):
    g = goal_multiplier(goal_diff)
    if g == 0.0:
        return 0.0
    return g * (2.2 / ((delta_elo * 0.001) + 2.2))


def result_score(goals_for, goals_against):
    if goals_for > goals_against:
        return 1.0
    if goals_for < goals_against:
        return 0.0
    return 0.5


def k_factor(matches_played):
    if matches_played < settings.ELO_NEW_TEAM_MATCHES:
        return settings.ELO_K_NEW
    return settings.ELO_K_DEFAULT


def compute_elo_update(
    home_elo,
    away_elo,
    home_goals,
    away_goals,
    home_played,
    away_played,
    home_advantage=None,
):
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE

    e_home, e_away = expected_probability(
        home_elo, away_elo, home_advantage=home_advantage, is_home=True
    )

    s_home = result_score(home_goals, away_goals)
    s_away = result_score(away_goals, home_goals)

    goal_diff = abs(home_goals - away_goals)

    if home_goals > away_goals:
        winner_elo, loser_elo = home_elo, away_elo
        delta_elo = winner_elo - loser_elo
    elif away_goals > home_goals:
        winner_elo, loser_elo = away_elo, home_elo
        delta_elo = winner_elo - loser_elo
    else:
        delta_elo = 0.0

    m = strength_multiplier(goal_diff, delta_elo) if goal_diff > 0 else 1.0

    k_home = k_factor(home_played)
    k_away = k_factor(away_played)

    home_delta = k_home * m * (s_home - e_home)
    away_delta = k_away * m * (s_away - e_away)

    return {
        "e_home": e_home,
        "e_away": e_away,
        "s_home": s_home,
        "s_away": s_away,
        "multiplier": m,
        "k_home": k_home,
        "k_away": k_away,
        "home_delta": home_delta,
        "away_delta": away_delta,
        "home_elo_new": home_elo + home_delta,
        "away_elo_new": away_elo + away_delta,
    }


def apply_elo_update(match):
    if match.elo_processed:
        return None
    if not match.has_result:
        return None

    home = match.home_team
    away = match.away_team

    result = compute_elo_update(
        home_elo=home.elo,
        away_elo=away.elo,
        home_goals=match.home_goals,
        away_goals=match.away_goals,
        home_played=home.matches_played,
        away_played=away.matches_played,
    )

    match.home_elo_before = home.elo
    match.away_elo_before = away.elo

    home.elo = result["home_elo_new"]
    away.elo = result["away_elo_new"]
    home.matches_played += 1
    away.matches_played += 1

    match.home_elo_after = home.elo
    match.away_elo_after = away.elo
    match.elo_processed = True

    home.save(update_fields=["elo", "matches_played"])
    away.save(update_fields=["elo", "matches_played"])
    match.save(update_fields=[
        "home_elo_before",
        "away_elo_before",
        "home_elo_after",
        "away_elo_after",
        "elo_processed",
    ])

    EloLog.objects.create(
        match=match,
        team=home,
        elo_before=result["home_elo_new"] - result["home_delta"],
        elo_after=result["home_elo_new"],
        delta=result["home_delta"],
    )
    EloLog.objects.create(
        match=match,
        team=away,
        elo_before=result["away_elo_new"] - result["away_delta"],
        elo_after=result["away_elo_new"],
        delta=result["away_delta"],
    )

    return result


def assign_initial_elo(team, competition, season=""):
    from elo.models import LeagueStrength
    strength = LeagueStrength.objects.filter(
        competition=competition, season=season
    ).first()
    if strength is not None:
        team.elo = strength.average_elo
    else:
        team.elo = settings.ELO_LEAGUE_INITIAL.get(
            competition.code, settings.ELO_DEFAULT
        )
    return team.elo


def recompute_league_strength(season=None):
    from elo.models import LeagueStrength
    from teams.models import TeamCompetition

    links = TeamCompetition.objects.all()
    if season:
        links = links.filter(season=season)

    updated = 0
    seen = set()
    for link in links.select_related("competition"):
        key = (link.competition_id, link.season)
        if key in seen:
            continue
        seen.add(key)

        team_ids = TeamCompetition.objects.filter(
            competition=link.competition, season=link.season
        ).values_list("team_id", flat=True)
        from teams.models import Team
        teams = Team.objects.filter(id__in=team_ids)
        if not teams:
            continue
        avg = sum(t.elo for t in teams) / teams.count()

        obj, created = LeagueStrength.objects.update_or_create(
            competition=link.competition,
            season=link.season,
            defaults={"average_elo": round(avg, 1)},
        )
        updated += 1
    return updated


def process_pending_matches(limit=None):
    pending = Match.objects.filter(
        elo_processed=False,
        status__in=[Match.Status.FINISHED, Match.Status.AWARDED],
        home_goals__isnull=False,
        away_goals__isnull=False,
    ).order_by("utc_date")
    if limit:
        pending = pending[:limit]
    processed = 0
    for match in pending:
        try:
            result = apply_elo_update(match)
            if result is not None:
                processed += 1
        except Exception:
            import logging
            logging.getLogger("alpha").exception(
                "Error aplicando Elo al partido %s", match.id_api
            )
    return processed

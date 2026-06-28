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


def k_factor(matches_played, competition=None):
    """K-factor según antigüedad del equipo y tipo de competición.

    Equipos nuevos (< ELO_NEW_TEAM_MATCHES) usan K mayor para converger
    rápido. En torneos internacionales (WC, WCQ, copas continentales) se
    aplica K mayor porque son partidos de mayor peso. Clubes profesionales
    usan K=20, ligas menores K=25 (ver docs/elo.md Paso 7).

    Clasificación de competición:
      * Internacional: en settings.ELO_INTERNATIONAL_LEAGUE_IDS → K=30.
      * Liga menor: catálogo semilla con initial_elo < ELO_MINOR_THRESHOLD → K=25.
      * Resto (clubes top): K=20.
    """
    if matches_played < settings.ELO_NEW_TEAM_MATCHES:
        return settings.ELO_K_NEW

    if competition is not None:
        intl_ids = getattr(settings, "ELO_INTERNATIONAL_LEAGUE_IDS", frozenset())
        if competition.id_api in intl_ids:
            return settings.ELO_K_INTERNATIONAL

        minor_threshold = getattr(settings, "ELO_MINOR_LEAGUE_THRESHOLD", 1400)
        af = getattr(settings, "API_FOOTBALL_LEAGUES_BY_ID", {}).get(
            competition.id_api
        )
        if af is not None and af["initial_elo"] < minor_threshold:
            return settings.ELO_K_MINOR

    return settings.ELO_K_DEFAULT


def compute_elo_update(
    home_elo,
    away_elo,
    home_goals,
    away_goals,
    home_played,
    away_played,
    home_advantage=None,
    status_short="",
    competition=None,
):
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE

    e_home, e_away = expected_probability(
        home_elo, away_elo, home_advantage=home_advantage, is_home=True
    )

    # Los partidos decididos por penales (status PEN) se tratan como empate
    # para Elo (S=0.5) sin importar el marcador: los penales no reflejan
    # fuerza relativa, solo desempate. Los goles usados son los de fulltime
    # (90 + extra time), ya guardados en home_goals/away_goals.
    is_penalty = status_short.upper() == "PEN"

    if is_penalty:
        s_home = 0.5
        s_away = 0.5
        goal_diff = 0
    else:
        s_home = result_score(home_goals, away_goals)
        s_away = result_score(away_goals, home_goals)
        goal_diff = abs(home_goals - away_goals)

    if goal_diff > 0:
        if home_goals > away_goals:
            winner_elo, loser_elo = home_elo, away_elo
        else:
            winner_elo, loser_elo = away_elo, home_elo
        delta_elo = winner_elo - loser_elo
        m = strength_multiplier(goal_diff, delta_elo)
    else:
        delta_elo = 0.0
        m = 1.0

    k_home = k_factor(home_played, competition)
    k_away = k_factor(away_played, competition)

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


def apply_elo_update(match, regenerate_forecasts=True):
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
        status_short=match.status_short,
        competition=match.competition,
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

    # Refrescar los pronósticos de los próximos partidos de ambos equipos
    # para que reflejen el nuevo Elo y la nueva forma reciente.
    # Se omite durante carga histórica masiva (process_pending_matches)
    # porque no tiene sentido regenerar pronósticos para partidos del pasado.
    if regenerate_forecasts:
        from forecasts.engine import regenerate_for_teams
        try:
            regenerated, fallback = regenerate_for_teams([home, away])
            result["forecasts_regenerated"] = regenerated
            result["forecasts_fallback"] = fallback
        except Exception:
            import logging
            logging.getLogger("alpha").exception(
                "Error refrescando pronósticos tras Elo en partido %s",
                match.id_api,
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
        # Catálogo semilla de calibración por id_api. Las ligas no
        # listadas usan ELO_DEFAULT y se recalibran tras el backfill.
        af = getattr(settings, "API_FOOTBALL_LEAGUES_BY_ID", {}).get(
            competition.id_api
        )
        if af is not None:
            team.elo = af["initial_elo"]
        else:
            team.elo = settings.ELO_DEFAULT
    return team.elo


def recompute_league_strength(season=None):
    from django.db.models import Avg

    from elo.models import LeagueStrength
    from teams.models import Competition, TeamCompetition

    # Una sola query agregada: promedio de Elo por (competición, temporada).
    qs = TeamCompetition.objects.values("competition_id", "season").annotate(
        avg_elo=Avg("team__elo")
    )
    if season:
        qs = qs.filter(season=season)

    rows = list(qs)
    if not rows:
        return 0

    # Resolver competiciones en una sola query.
    comp_ids = {row["competition_id"] for row in rows if row["avg_elo"] is not None}
    comps = {c.id: c for c in Competition.objects.filter(id__in=comp_ids)}

    updated = 0
    for row in rows:
        if row["avg_elo"] is None:
            continue
        competition = comps.get(row["competition_id"])
        if competition is None:
            continue
        LeagueStrength.objects.update_or_create(
            competition=competition,
            season=row["season"],
            defaults={"average_elo": round(row["avg_elo"], 1)},
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
            result = apply_elo_update(
                match, regenerate_forecasts=False
            )
            if result is not None:
                processed += 1
        except Exception:
            import logging
            logging.getLogger("alpha").exception(
                "Error aplicando Elo al partido %s", match.id_api
            )
    return processed

import math

from django.conf import settings

from elo.models import EloLog
from matches.models import Match
from teams.models import Competition


def expected_probability(elo_a, elo_b, home_advantage=None, is_neutral=False):
    """Probabilidad esperada de A (local) contra B (visitante).

    docs/elo.md: la localía modifica únicamente el cálculo de la
    probabilidad esperada. is_neutral=True (Mundial, fases finales en
    sede neutral) anula la ventaja de localía.
    """
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE
    advantage = 0 if is_neutral else home_advantage
    diff = (elo_a + advantage) - elo_b
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

    docs/elo.md §Factor K:
      Mundial 30, Eliminatorias 25, Copa continental 25, Primera
      división y Copas nacionales 20, Amistosos 15. Equipos nuevos
      (< ELO_NEW_TEAM_MATCHES) usan K=40 para converger rápido,
      ignorando el tipo de competición.
    """
    if matches_played < settings.ELO_NEW_TEAM_MATCHES:
        return settings.ELO_K_NEW

    if competition is None:
        return settings.ELO_K_DEFAULT

    kind = getattr(competition, "kind", None) or Competition.Kind.LEAGUE
    return {
        Competition.Kind.WORLD_CUP: settings.ELO_K_WORLD_CUP,
        Competition.Kind.QUALIFIERS: settings.ELO_K_QUALIFIERS,
        Competition.Kind.CONTINENTAL: settings.ELO_K_CONTINENTAL,
        Competition.Kind.CUP: settings.ELO_K_CUP,
        Competition.Kind.FRIENDLY: settings.ELO_K_FRIENDLY,
        Competition.Kind.LEAGUE: settings.ELO_K_DEFAULT,
        Competition.Kind.INTERNATIONAL: settings.ELO_K_CONTINENTAL,
    }.get(kind, settings.ELO_K_DEFAULT)


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
    is_neutral=False,
):
    if home_advantage is None:
        home_advantage = settings.ELO_HOME_ADVANTAGE

    e_home, e_away = expected_probability(
        home_elo,
        away_elo,
        home_advantage=home_advantage,
        is_neutral=is_neutral,
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

    home_advantage = (
        match.competition.home_advantage
        if match.competition_id else settings.ELO_HOME_ADVANTAGE
    )
    result = compute_elo_update(
        home_elo=home.elo,
        away_elo=away.elo,
        home_goals=match.home_goals,
        away_goals=match.away_goals,
        home_played=home.matches_played,
        away_played=away.matches_played,
        status_short=match.status_short,
        competition=match.competition,
        is_neutral=match.is_neutral,
        home_advantage=home_advantage,
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


def regress_elo(
    season,
    regress_factor=0.90,
    league_weight=0.10,
    use_prior_league=False,
):
    """Regresión de Elo entre temporadas (docs/elo.md §Regresión).

    EloNuevo = regress_factor·EloAnterior + league_weight·EloPromedioLiga

    Por defecto (use_prior_league=False) usa el LeagueStrength de la
    propia `season` (requiere que ya exista con average_elo real): es el
    modo del comando manual `regress_elo`, pensado para ejecutarse a
    mitad/final de temporada cuando ya hay datos recalculados.

    Con use_prior_league=True (uso desde daily_update al detectar el
    inicio de temporada nueva) usa la última LeagueStrength *anterior*
    a `season` de cada competición donde el equipo participó en cualquier
    temporada previa. Esto permite aplicar la regresión *antes* de que
    la nueva temporada acumule partidos.

    Idempotente: marca Team.last_regressed_season y omite equipos ya
    regresados a `season` (o a una posterior).

    Devuelve el número de equipos actualizados.
    """
    from django.db.models import Avg

    from elo.models import LeagueStrength
    from teams.models import Team, TeamCompetition

    updated = 0
    teams = Team.objects.exclude(last_regressed_season=season)
    for team in teams.iterator():
        if use_prior_league:
            # Competiciones donde el equipo estuvo en alguna temporada
            # anterior a `season` (para tener un LeagueStrength plausible).
            comp_ids = list(
                TeamCompetition.objects.filter(
                    team=team, season__lt=season
                ).values_list("competition_id", flat=True).distinct()
            )
            if not comp_ids:
                continue
            # Última LeagueStrength anterior a `season` por competición.
            # Tomamos la más reciente de cada una y promediamos.
            avgs = []
            for comp_id in comp_ids:
                last_avg = LeagueStrength.objects.filter(
                    competition_id=comp_id, season__lt=season
                ).order_by("-season").values_list("average_elo", flat=True).first()
                if last_avg is not None:
                    avgs.append(last_avg)
            if not avgs:
                continue
            avg = sum(avgs) / len(avgs)
        else:
            # Modo manual original: LeagueStrength de la propia `season`.
            comp_ids = list(
                TeamCompetition.objects.filter(
                    team=team, season=season
                ).values_list("competition_id", flat=True)
            )
            if not comp_ids:
                continue
            avg = LeagueStrength.objects.filter(
                competition_id__in=comp_ids, season=season
            ).aggregate(avg=Avg("average_elo"))["avg"]
            if avg is None:
                continue
        new_elo = regress_factor * team.elo + league_weight * avg
        team.elo = round(new_elo, 2)
        team.last_regressed_season = season
        team.save(update_fields=["elo", "last_regressed_season"])
        updated += 1
    return updated


def seasons_needing_regression():
    """Detecta qué temporadas requieren regresión de Elo al inicio de
    una nueva temporada.

    Compara `Competition.current_season` (refrescado por sync_competitions
    desde football-data.org) contra la última `last_regressed_season`
    observada entre los equipos ligados a esa competición. Si ningún
    equipo fue regresado a `current_season` (o solo a una temporada
    previa), la temporada `current_season` se considera pendiente.

    Devuelve una lista ordenada (asc) de strings de temporada únicos.
    Diseñado para ser llamado desde daily_update: es idempotente — una
    vez aplicada la regresión a `current_season`, el set queda vacío
    hasta que la competición avance de nuevo.
    """
    from django.db.models import Max

    from teams.models import Competition, Team, TeamCompetition

    pending = set()
    qs = (
        Competition.objects.exclude(current_season="")
        .values("id", "current_season")
    )
    for comp in qs:
        target = comp["current_season"]
        if not target:
            continue
        # Máxima `last_regressed_season` entre todos los equipos que
        # alguna vez jugaron esta competición (en cualquier temporada).
        team_ids = TeamCompetition.objects.filter(
            competition_id=comp["id"]
        ).values_list("team_id", flat=True).distinct()
        latest = (
            Team.objects.filter(id__in=team_ids)
            .aggregate(m=Max("last_regressed_season"))["m"]
            or ""
        )
        if latest < target:
            pending.add(target)
    return sorted(pending)

from django.conf import settings
from django.utils.dateparse import parse_datetime

from api_client.client import FootballDataClient
from elo.engine import assign_initial_elo
from elo.models import LeagueStrength
from matches.models import Match
from teams.models import Competition, Team, TeamCompetition

SOURCE = Competition.Source.FOOTBALLDATA


def ensure_competition(comp_data, client=None, enrich=False):
    comp_id = comp_data.get("id")
    comp_code = comp_data.get("code", "")
    if comp_id is None:
        return None, False

    competition = Competition.objects.filter(
        id_api=comp_id, source=SOURCE
    ).first()
    if competition is not None:
        return competition, False

    full_data = None
    if enrich and comp_code and client is not None:
        try:
            full_data = client.get_competition(comp_code)
        except Exception:
            pass

    if full_data:
        area = full_data.get("area", {}) or {}
        season = full_data.get("currentSeason", {}) or {}
        season_str = season.get("startDate", "")[:4] or ""
        competition = Competition.objects.create(
            id_api=full_data["id"],
            source=SOURCE,
            code=full_data.get("code", comp_code),
            name=full_data.get("name", ""),
            area_name=area.get("name", ""),
            area_code=area.get("code", ""),
            plan=full_data.get("plan", ""),
            current_season=season_str,
        )
    else:
        competition = Competition.objects.create(
            id_api=comp_id,
            source=SOURCE,
            code=comp_code,
            name=comp_data.get("name", ""),
        )
        season_str = ""

    if season_str:
        initial = settings.ELO_LEAGUE_INITIAL.get(
            comp_code, settings.ELO_DEFAULT
        )
        LeagueStrength.objects.get_or_create(
            competition=competition,
            season=season_str,
            defaults={"average_elo": initial},
        )

    return competition, True


def ensure_team(team_data, competition, season_str, client=None, enrich=False):
    team_id = team_data.get("id")
    if team_id is None:
        return None, False

    team = Team.objects.filter(id_api=team_id, source=SOURCE).first()
    if team is not None:
        # Asegurar el link TeamCompetition aunque el equipo ya exista,
        # porque puede participar en una competición/temporada nueva.
        if season_str:
            TeamCompetition.objects.get_or_create(
                team=team,
                competition=competition,
                season=season_str,
            )
        return team, False

    # Si no existe con source=footballdata, buscar por nombre en
    # api-football. Esto evita duplicar selecciones nacionales que ya
    # tienen historial (Elo, partidos) bajo source=apifootball.
    team_name = team_data.get("name", "")
    if team_name:
        existing = Team.objects.filter(
            name=team_name, source=Team.Source.APIFOOTBALL
        ).first()
        if existing is not None:
            if season_str:
                TeamCompetition.objects.get_or_create(
                    team=existing,
                    competition=competition,
                    season=season_str,
                )
            return existing, False

    full_data = None
    if enrich and client is not None:
        try:
            full_data = client.get_team(team_id)
        except Exception:
            pass

    if full_data:
        team = Team.objects.create(
            id_api=full_data["id"],
            source=SOURCE,
            name=full_data.get("name", ""),
            short_name=full_data.get("shortName", ""),
            tla=full_data.get("tla", ""),
            crest_url=full_data.get("crest", ""),
            founded=full_data.get("founded"),
            venue=full_data.get("venue", ""),
            website=full_data.get("website", ""),
        )
    else:
        team = Team.objects.create(
            id_api=team_id,
            source=SOURCE,
            name=team_data.get("name", ""),
            short_name=team_data.get("shortName", ""),
            tla=team_data.get("tla", ""),
            crest_url=team_data.get("crest", ""),
        )

    assign_initial_elo(team, competition, season=season_str)
    team.save(update_fields=["elo"])

    if season_str:
        TeamCompetition.objects.get_or_create(
            team=team,
            competition=competition,
            season=season_str,
        )

    return team, True


def save_match(data, competition, home, away):
    match_id = data.get("id")
    if match_id is None:
        return None, False

    season_data = data.get("season", {}) or {}
    season_str = (season_data.get("startDate", "") or "")[:4] or ""

    score = data.get("score", {}) or {}
    full_time = score.get("fullTime", {}) or {}
    home_goals = full_time.get("home")
    away_goals = full_time.get("away")

    utc_date_raw = data.get("utcDate")
    if not utc_date_raw:
        return None, False
    utc_date = parse_datetime(utc_date_raw)
    if utc_date is None:
        return None, False

    match, created = Match.objects.update_or_create(
        id_api=match_id,
        source=SOURCE,
        defaults={
            "competition": competition,
            "season": season_str,
            "matchday": data.get("matchday"),
            "stage": data.get("stage") or "",
            "group": data.get("group") or "",
            "status": data.get("status", Match.Status.SCHEDULED),
            "utc_date": utc_date,
            "home_team": home,
            "away_team": away,
            "home_goals": home_goals,
            "away_goals": away_goals,
        },
    )
    return match, created

"""Mapeo de respuestas de API-Football al modelo de Alpha Bet.

Cada funcion ensure_* garantiza la existencia del objeto (competition, team,
match) con source='apifootball'. El mapeo de status y goles sigue las
convenciones de docs/api_football.md y docs/elo.md (penales = empate).
"""
from django.utils.dateparse import parse_datetime

from elo.engine import assign_initial_elo
from matches.models import Match
from teams.models import Competition, Team, TeamCompetition

SOURCE = Competition.Source.APIFOOTBALL

# Mapeo de status de API-Football a Match.Status.
STATUS_MAP = {
    "NS": Match.Status.SCHEDULED,
    "TBD": Match.Status.SCHEDULED,
    "1H": Match.Status.IN_PLAY,
    "HT": Match.Status.PAUSED,
    "2H": Match.Status.IN_PLAY,
    "ET": Match.Status.IN_PLAY,
    "LIVE": Match.Status.IN_PLAY,
    "BT": Match.Status.IN_PLAY,
    "FT": Match.Status.FINISHED,
    "AET": Match.Status.FINISHED,
    "PEN": Match.Status.FINISHED,
    "PST": Match.Status.POSTPONED,
    "CANC": Match.Status.CANCELLED,
    "ABD": Match.Status.CANCELLED,
    "AWD": Match.Status.AWARDED,
    "SUSP": Match.Status.SUSPENDED,
    "INT": Match.Status.SUSPENDED,
}


def _map_status(short):
    return STATUS_MAP.get(short, Match.Status.SCHEDULED)


def ensure_competition_af(league_data, season_str=""):
    """Crea o actualiza una competicion desde un bloque league de API-Football.

    Acepta tanto la estructura de /leagues (league + country como objetos
    separados) como la de /fixtures (todo dentro de league, country como
    string). Si season_str se proporciona, crea LeagueStrength.
    """
    league = league_data.get("league", {}) or league_data
    league_id = league.get("id")
    if league_id is None:
        return None, False

    # country puede ser objeto (en /leagues), string (en /fixtures) o estar
    # ausente. Se normaliza a {name, code}.
    country_raw = league_data.get("country")
    if country_raw is None:
        country_raw = league.get("country")
    if isinstance(country_raw, str):
        country = {"name": country_raw, "code": ""}
    elif isinstance(country_raw, dict):
        country = country_raw
    else:
        country = {}

    code = str(league_id)
    defaults = {
        "code": code,
        "name": league.get("name", ""),
        "area_name": country.get("name", ""),
        "area_code": country.get("code", ""),
        "plan": league.get("type", ""),
        "current_season": season_str,
    }

    competition, created = Competition.objects.update_or_create(
        id_api=league_id,
        source=SOURCE,
        defaults=defaults,
    )

    if season_str:
        from django.conf import settings
        af = settings.API_FOOTBALL_LEAGUES_BY_CODE.get(code)
        initial = af["initial_elo"] if af else settings.ELO_DEFAULT
        from elo.models import LeagueStrength
        LeagueStrength.objects.get_or_create(
            competition=competition,
            season=season_str,
            defaults={"average_elo": initial},
        )

    return competition, created


def ensure_team_af(team_data, competition, season_str=""):
    """Crea o actualiza un equipo desde un bloque teams de API-Football.

    team_data es r['team'] (con venue opcional en r['venue']).
    """
    team = team_data.get("team", {}) or team_data
    venue = team_data.get("venue", {}) or {}
    team_id = team.get("id")
    if team_id is None:
        return None, False

    defaults = {
        "name": team.get("name", ""),
        "short_name": team.get("name", ""),
        "tla": team.get("code", ""),
        "crest_url": team.get("logo", ""),
        "founded": team.get("founded"),
        "venue": venue.get("name", ""),
    }

    team_obj, created = Team.objects.update_or_create(
        id_api=team_id,
        source=SOURCE,
        defaults=defaults,
    )

    if created:
        assign_initial_elo(team_obj, competition, season=season_str)
        team_obj.save(update_fields=["elo"])

    if season_str:
        TeamCompetition.objects.get_or_create(
            team=team_obj,
            competition=competition,
            season=season_str,
        )

    return team_obj, created


def save_match_af(fixture_data, competition, home, away, season_str=""):
    """Crea o actualiza un partido desde un fixture de API-Football.

    Goles: score.fulltime (90 + extra time). Si status=PEN, Elo tratara el
    resultado como empate (la logica esta en apply_elo_update, que usa los
    goles fulltime directamente).
    """
    fixture = fixture_data.get("fixture", {}) or {}
    match_id = fixture.get("id")
    if match_id is None:
        return None, False

    date_raw = fixture.get("date")
    if not date_raw:
        return None, False
    utc_date = parse_datetime(date_raw)
    if utc_date is None:
        return None, False

    score = fixture_data.get("score", {}) or {}
    full_time = score.get("fulltime", {}) or {}
    home_goals = full_time.get("home")
    away_goals = full_time.get("away")

    status_short = (fixture.get("status", {}) or {}).get("short", "")
    status = _map_status(status_short)

    league = fixture_data.get("league", {}) or {}
    stage = league.get("round") or ""

    match, created = Match.objects.update_or_create(
        id_api=match_id,
        source=SOURCE,
        defaults={
            "competition": competition,
            "season": season_str,
            "matchday": None,
            "stage": stage,
            "group": "",
            "status": status,
            "utc_date": utc_date,
            "home_team": home,
            "away_team": away,
            "home_goals": home_goals,
            "away_goals": away_goals,
        },
    )
    return match, created

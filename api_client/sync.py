"""Mapeo de respuestas de football-data.org al modelo de Alpha Bet.

Cada función ensure_* garantiza la existencia del objeto (competition,
team, match). El mapeo de status y goles sigue las convenciones de
docs/api_football.md y docs/elo.md (penales = empate para Elo).
"""
from django.conf import settings
from django.utils.dateparse import parse_datetime

from elo.engine import assign_initial_elo
from matches.models import Match
from teams.models import Competition, Team, TeamCompetition

# Mapeo de status de football-data.org a Match.Status.
STATUS_MAP = {
    "SCHEDULED": Match.Status.SCHEDULED,
    "TIMED": Match.Status.SCHEDULED,
    "LIVE": Match.Status.IN_PLAY,
    "IN_PLAY": Match.Status.IN_PLAY,
    "PAUSED": Match.Status.PAUSED,
    "FINISHED": Match.Status.FINISHED,
    "POSTPONED": Match.Status.POSTPONED,
    "SUSPENDED": Match.Status.SUSPENDED,
    "CANCELLED": Match.Status.CANCELLED,
}

# Mapeo de score.duration a status_short. El motor de Elo detecta "PEN"
# para tratar partidos decididos por penales como empate.
DURATION_MAP = {
    "REGULAR": "FT",
    "EXTRA_TIME": "AET",
    "PENALTY_SHOOTOUT": "PEN",
}


def _map_status(status):
    return STATUS_MAP.get(status, Match.Status.SCHEDULED)


def _map_duration(duration):
    """Convierte score.duration en status_short (FT/AET/PEN)."""
    return DURATION_MAP.get(duration, "FT")


def _kind_from_competition(code, area_name=""):
    """Infiere Competition.Kind desde el código/área de football-data.org."""
    code = (code or "").upper()
    if code == "CL":
        return Competition.Kind.CONTINENTAL
    if code == "WC":
        return Competition.Kind.WORLD_CUP
    if code == "EC":
        return Competition.Kind.INTERNATIONAL
    return Competition.Kind.LEAGUE


def ensure_competition(comp_data, season_str=""):
    """Crea o actualiza una competición desde un objeto de
    football-data.org (/v4/competitions o el bloque embebido en un
    match). Si season_str se proporciona, crea LeagueStrength.
    """
    comp_id = comp_data.get("id")
    if comp_id is None:
        return None, False

    code = comp_data.get("code") or str(comp_id)
    area = comp_data.get("area", {}) or {}
    area_name = area.get("name", "") if isinstance(area, dict) else ""

    kind = _kind_from_competition(code, area_name)

    defaults = {
        "code": code,
        "name": comp_data.get("name", ""),
        "area_name": area_name,
        "area_code": str(area.get("id", "")) if isinstance(area, dict) else "",
        "plan": comp_data.get("plan", ""),
    }
    # Solo sobrescribe current_season si viene explicitamente en el objeto
    # de /v4/competitions (con currentSeason). El bloque embebido en un
    # match no lo trae.
    current = comp_data.get("currentSeason")
    if isinstance(current, dict) and current.get("startDate"):
        defaults["current_season"] = str(current["startDate"][:4])

    # kind/home_advantage solo al crear (no pisar ajustes manuales).
    competition, created = Competition.objects.update_or_create(
        id_api=comp_id,
        defaults=defaults,
    )
    if created:
        competition.kind = kind
        # Localía por defecto: nacional 80, internacional/Mundial/neutral 0.
        if kind in (
            Competition.Kind.WORLD_CUP,
            Competition.Kind.INTERNATIONAL,
            Competition.Kind.CONTINENTAL,
        ):
            competition.home_advantage = 0
        competition.save(update_fields=["kind", "home_advantage"])

    if season_str:
        from elo.models import LeagueStrength
        LeagueStrength.objects.get_or_create(
            competition=competition,
            season=season_str,
            defaults={"average_elo": settings.ELO_DEFAULT},
        )

    return competition, created


def ensure_team(team_data, competition, season_str=""):
    """Crea o actualiza un equipo desde un bloque team de
    football-data.org (embebido en match o de /v4/teams).
    """
    team_id = team_data.get("id")
    if team_id is None:
        return None, False

    area = team_data.get("area", {}) or {}
    country = area.get("name", "") if isinstance(area, dict) else ""

    defaults = {
        "name": team_data.get("name", ""),
        "tla": team_data.get("tla", "") or "",
        "crest_url": team_data.get("crest", "") or "",
        "founded": team_data.get("founded"),
        "venue": team_data.get("venue", "") or "",
        "country": country,
        "short_name": team_data.get("shortName", "") or "",
        "website": team_data.get("website", "") or "",
        "club_colors": team_data.get("clubColors", "") or "",
    }

    team_obj, created = Team.objects.update_or_create(
        id_api=team_id,
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


def _importance_from_competition(competition):
    """Importancia competitiva derivada del kind de la competición."""
    kind = (competition.kind if competition else None) or Competition.Kind.LEAGUE
    return {
        Competition.Kind.LEAGUE: Match.Importance.LEAGUE,
        Competition.Kind.CUP: Match.Importance.CUP,
        Competition.Kind.CONTINENTAL: Match.Importance.KNOCKOUT,
        Competition.Kind.WORLD_CUP: Match.Importance.INTERNATIONAL,
        Competition.Kind.INTERNATIONAL: Match.Importance.INTERNATIONAL,
        Competition.Kind.QUALIFIERS: Match.Importance.KNOCKOUT,
        Competition.Kind.FRIENDLY: Match.Importance.FRIENDLY,
        Competition.Kind.OTHER: Match.Importance.LEAGUE,
    }.get(kind, Match.Importance.LEAGUE)


def _neutral_default(competition):
    """Sede neutral por defecto según el tipo de competición.

    Las fases finales internacionales (Mundial, torneos de selecciones,
    copas continentales) se disputan en sede neutral: la ventaja de
    localía no aplica (docs/elo.md §Ventaja de localía).
    """
    kind = (competition.kind if competition else None) or Competition.Kind.LEAGUE
    return kind in (
        Competition.Kind.WORLD_CUP,
        Competition.Kind.INTERNATIONAL,
        Competition.Kind.CONTINENTAL,
    )


def _rest_days(team, before_date):
    """Días desde el último partido finalizado del equipo antes de
    `before_date`. None si no hay historial."""
    last = (
        Match.objects.filter(
            _team_q(team),
            status=Match.Status.FINISHED,
            utc_date__lt=before_date,
            home_goals__isnull=False,
            away_goals__isnull=False,
        )
        .order_by("-utc_date")
        .first()
    )
    if last is None:
        return None
    return max((before_date - last.utc_date).days, 0)


def _team_q(team):
    from django.db.models import Q
    return Q(home_team=team) | Q(away_team=team)


def _round_label(match_data):
    """Construye un label legible de ronda desde stage/group/matchday."""
    stage = match_data.get("stage", "") or ""
    group = match_data.get("group", "") or ""
    matchday = match_data.get("matchday")
    parts = []
    if stage:
        parts.append(stage.replace("_", " ").title())
    if group:
        parts.append(group)
    if matchday is not None:
        parts.append(f"MD {matchday}")
    return " · ".join(parts)


def save_match(match_data, competition, home, away, season_str=""):
    """Crea o actualiza un partido desde un objeto match de
    football-data.org. Goles: score.fullTime (90 + extra time). Si
    duration=PENALTY_SHOOTOUT, Elo tratará el resultado como empate
    (status_short="PEN" → apply_elo_update lo detecta). Puebla sede
    neutral, estadio, importancia y descanso de cada equipo.
    """
    match_id = match_data.get("id")
    if match_id is None:
        return None, False

    date_raw = match_data.get("utcDate")
    if not date_raw:
        return None, False
    utc_date = parse_datetime(date_raw)
    if utc_date is None:
        return None, False

    score = match_data.get("score", {}) or {}
    duration = score.get("duration")
    # football-data.org usa fullTime.home/away (no homeTeam/awayTeam).
    # Para PENALTY_SHOOTOUT, fullTime incluye los goles de penales (ej.
    # 3-4 cuando el partido fue 1-1); el resultado futbolístico real es
    # regularTime + extraTime (docs/elo.md: los penales no cuentan como
    # goles del partido). Elo trata los PEN como empate vía status_short.
    if duration == "PENALTY_SHOOTOUT":
        regular = score.get("regularTime", {}) or {}
        extra = score.get("extraTime", {}) or {}
        rh = regular.get("home")
        ra = regular.get("away")
        eh = extra.get("home")
        ea = extra.get("away")
        home_goals = (rh or 0) + (eh or 0) if rh is not None else None
        away_goals = (ra or 0) + (ea or 0) if ra is not None else None
    else:
        full_time = score.get("fullTime", {}) or {}
        home_goals = full_time.get("home")
        away_goals = full_time.get("away")

    status = _map_status(match_data.get("status"))
    status_short = _map_duration(duration)

    venue_name = match_data.get("venue", "") or ""
    is_neutral = _neutral_default(competition)
    importance = _importance_from_competition(competition)
    round_label = _round_label(match_data)

    defaults = {
        "competition": competition,
        "season": season_str,
        "round": round_label,
        "stage": match_data.get("stage", "") or "",
        "group": match_data.get("group", "") or "",
        "matchday": match_data.get("matchday"),
        "status": status,
        "status_short": status_short,
        "utc_date": utc_date,
        "home_team": home,
        "away_team": away,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "venue": venue_name,
        "is_neutral": is_neutral,
        "importance": importance,
    }

    match, created = Match.objects.update_or_create(
        id_api=match_id,
        defaults=defaults,
    )

    if home is not None and away is not None:
        if created or match.rest_days_home is None:
            match.rest_days_home = _rest_days(home, utc_date)
        if created or match.rest_days_away is None:
            match.rest_days_away = _rest_days(away, utc_date)
        match.save(update_fields=["rest_days_home", "rest_days_away"])

    return match, created


def discover_competitions(competitions_response):
    """Filtra y crea Competition desde la respuesta de /v4/competitions.

    Conserva solo las competiciones del plan Free
    (settings.FOOTBALL_DATA_FREE_COMPETITION_CODES). Retorna
    (creadas, actualizadas, omitidas).
    """
    free_codes = settings.FOOTBALL_DATA_FREE_COMPETITION_CODES
    created = 0
    updated = 0
    skipped = 0
    for entry in competitions_response:
        code = (entry.get("code") or "").upper()
        if code not in free_codes:
            skipped += 1
            continue
        competition, was_created = ensure_competition(entry)
        if competition is None:
            skipped += 1
            continue
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated, skipped

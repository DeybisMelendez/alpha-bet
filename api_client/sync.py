"""Mapeo de respuestas de API-Football al modelo de Alpha Bet.

Cada función ensure_* garantiza la existencia del objeto (competition,
team, match). El mapeo de status y goles sigue las convenciones de
docs/api_football.md y docs/elo.md (penales = empate para Elo).
"""
from django.utils.dateparse import parse_datetime

from elo.engine import assign_initial_elo
from matches.models import Match
from stats.models import MatchStatistics
from teams.models import Competition, Team, TeamCompetition

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

# Mapeo de tipo de estadística de API-Football a campo de MatchStatistics.
# Las claves son los strings exactos que devuelve /fixtures/statistics.
STATS_TYPE_MAP = {
    "shots on goal": "shots_on_goal",
    "shots off goal": "shots_off_goal",
    "total shots": "shots_total",
    "blocked shots": "shots_blocked",
    "shots insidebox": "shots_inside_box",
    "shots outsidebox": "shots_outside_box",
    "shots inside box": "shots_inside_box",
    "shots outside box": "shots_outside_box",
    "ball possession": "possession",
    "possession": "possession",
    "possession (%)": "possession",
    "corner kicks": "corners",
    "offsides": "offsides",
    "fouls": "fouls_committed",
    "yellow cards": "yellow_cards",
    "red cards": "red_cards",
    "goalkeeper saves": "goalkeeper_saves",
    "passes total": "passes_total",
    "passes accurate": "passes_accurate",
    "passing accuracy": "passes_accurate",
}


def _map_status(short):
    return STATUS_MAP.get(short, Match.Status.SCHEDULED)


def ensure_competition(league_data, season_str=""):
    """Crea o actualiza una competición desde un bloque league de
    API-Football. Acepta tanto la estructura de /leagues (league +
    country como objetos separados) como la de /fixtures (todo dentro
    de league, country como string). Si season_str se proporciona,
    crea LeagueStrength.
    """
    league = league_data.get("league", {}) or league_data
    league_id = league.get("id")
    if league_id is None:
        return None, False

    # country puede ser objeto (en /leagues), string (en /fixtures) o
    # estar ausente. Se normaliza a {name, code}.
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
        "league_type": league.get("type", ""),
        "logo": league.get("logo", ""),
        "current_season": season_str,
    }

    competition, created = Competition.objects.update_or_create(
        id_api=league_id,
        defaults=defaults,
    )

    if season_str:
        from elo.models import LeagueStrength
        LeagueStrength.objects.get_or_create(
            competition=competition,
            season=season_str,
            defaults={"average_elo": settings.ELO_DEFAULT},
        )

    return competition, created


def ensure_team(team_data, competition, season_str=""):
    """Crea o actualiza un equipo desde un bloque teams de API-Football.
    team_data es r['team'] (con venue opcional en r['venue']).
    """
    team = team_data.get("team", {}) or team_data
    venue = team_data.get("venue", {}) or {}
    team_id = team.get("id")
    if team_id is None:
        return None, False

    country_name = ""
    if isinstance(team_data.get("country"), str):
        country_name = team_data["country"]
    else:
        country_name = team.get("country", "") or ""

    defaults = {
        "name": team.get("name", ""),
        "tla": team.get("code", ""),
        "crest_url": team.get("logo", ""),
        "founded": team.get("founded"),
        "venue": venue.get("name", ""),
        "country": country_name,
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
    """Importancia competitiva derivada del kind de la competición.

    docs/pronosticos_extra.md §Variables contextuales. El campo Match.importance
    etiqueta el partido para futuros ajustes de modelos secundarios.
    """
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
    localía no aplica (docs/elo.md §Ventaja de localía). El campo
    venue.neutral de API-Football, cuando está presente, tiene
    precedencia y sobreescribe este default.
    """
    kind = (competition.kind if competition else None) or Competition.Kind.LEAGUE
    return kind in (
        Competition.Kind.WORLD_CUP,
        Competition.Kind.INTERNATIONAL,
        Competition.Kind.CONTINENTAL,
    )


def _rest_days(team, before_date):
    """Días desde el último partido finalizado del equipo antes de
    `before_date`. None si no hay historial (docs/api.md §Variables
    contextuales)."""
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


def save_match(fixture_data, competition, home, away, season_str=""):
    """Crea o actualiza un partido desde un fixture de API-Football.
    Goles: score.fulltime (90 + extra time). Si status=PEN, Elo tratará
    el resultado como empate (la lógica está en apply_elo_update, que
    usa los goles fulltime directamente). Puebla además sede neutral,
    estadio, árbitro, importancia y descanso de cada equipo.
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

    status_short_raw = (fixture.get("status", {}) or {}).get("short", "")
    status = _map_status(status_short_raw)

    league = fixture_data.get("league", {}) or {}
    round_name = league.get("round") or ""

    venue = fixture.get("venue", {}) or {}
    venue_name = venue.get("name", "") or ""
    # API-Football marca venue.neutral como bool (cuando está presente).
    neutral_raw = venue.get("neutral")
    if neutral_raw is None:
        is_neutral = _neutral_default(competition)
    else:
        is_neutral = bool(neutral_raw)

    referee = fixture.get("referee") or ""
    importance = _importance_from_competition(competition)

    defaults = {
        "competition": competition,
        "season": season_str,
        "round": round_name,
        "status": status,
        "status_short": status_short_raw,
        "utc_date": utc_date,
        "home_team": home,
        "away_team": away,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "venue": venue_name,
        "referee": referee,
        "is_neutral": is_neutral,
        "importance": importance,
    }

    match, created = Match.objects.update_or_create(
        id_api=match_id,
        defaults=defaults,
    )

    # Días de descanso: solo recalculamos si el partido ya tiene fecha
    # y equipo. Es costoso pero razonable por partido. Omitimos en
    # partidos historicos masivos importados vía load_history porque el
    # backfill de larga cola ya no aporta descanso relevante.
    if home is not None and away is not None:
        # Solo actualiza si no estaba ya calculado (evita quemar DB
        # en cada re-sync del mismo partido).
        if created or match.rest_days_home is None:
            match.rest_days_home = _rest_days(home, utc_date)
        if created or match.rest_days_away is None:
            match.rest_days_away = _rest_days(away, utc_date)
        match.save(update_fields=["rest_days_home", "rest_days_away"])

    return match, created


def _parse_stat_value(field, raw):
    """Convierte el valor crudo de API-Football al tipo correcto del campo."""
    if raw is None:
        return None
    if field == "possession":
        # Suele venir como "55%" o "55".
        s = str(raw).strip().replace("%", "")
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _score_half_goals(fixture_data):
    """Goles por equipo en primero y segundo tiempo (o None si el
    endpoint no trae halftime)."""
    score = fixture_data.get("score", {}) or {}
    ht = score.get("halftime", {}) or {}
    ft = score.get("fulltime", {}) or {}
    ht_h = ht.get("home")
    ht_a = ht.get("away")
    ft_h = ft.get("home")
    ft_a = ft.get("away")
    out = {}
    if ht_h is not None and ft_h is not None:
        out["home_first"] = ht_h
        out["home_second"] = max(ft_h - (ht_h or 0), 0)
    if ht_a is not None and ft_a is not None:
        out["away_first"] = ht_a
        out["away_second"] = max(ft_a - (ht_a or 0), 0)
    return out


def save_match_statistics(match, client, fixture_data=None):
    """Descarga y persiste las estadísticas por equipo de un partido.

    Crea/actualiza dos filas de MatchStatistics (una por equipo). Si la
    respuesta viene vacía (fixture sin stats disponibles) no hace nada.

    `fixture_data` opcional permite completar goles por tiempo (half/
    second) desde el fixture ya consultado sin llamada extra.
    """
    teams_data = client.get_fixture_statistics(match.id_api)
    if not teams_data:
        return 0

    half = _score_half_goals(fixture_data) if fixture_data else {}

    created = 0
    for entry in teams_data:
        team_info = entry.get("team", {}) or {}
        team_id = team_info.get("id")
        team = Team.objects.filter(id_api=team_id).first()
        if team is None:
            continue
        is_home = team.pk == match.home_team_id

        defaults = {"team": team, "is_home": is_home}
        if is_home:
            if "home_first" in half:
                defaults["goals_first_half"] = half["home_first"]
                defaults["goals_second_half"] = half["home_second"]
        else:
            if "away_first" in half:
                defaults["goals_first_half"] = half["away_first"]
                defaults["goals_second_half"] = half["away_second"]

        for stat in entry.get("statistics", []) or []:
            type_name = (stat.get("type") or "").strip().lower()
            field = STATS_TYPE_MAP.get(type_name)
            if field is None:
                continue
            parsed = _parse_stat_value(field, stat.get("value"))
            if parsed is not None:
                defaults[field] = parsed

        MatchStatistics.objects.update_or_create(
            match=match,
            team=team,
            defaults=defaults,
        )
        created += 1
    return created


def discover_leagues(leagues_response):
    """Filtra y crea Competition desde la respuesta de /leagues.
    Descarta competiciones femenil/juvenil/futsal/beach/esports por
    nombre. Retorna (creadas, actualizadas, omitidas).
    """
    import re
    skip_re = re.compile(
        r"\b(women|femenino|femenil|youth|juvenil|futsal|beach|esports?)\b",
        re.IGNORECASE,
    )
    created = 0
    updated = 0
    skipped = 0
    for entry in leagues_response:
        league = entry.get("league", {}) or {}
        league_type = league.get("type", "")
        if league_type and league_type not in ("league", "cup"):
            skipped += 1
            continue
        name = league.get("name", "")
        if skip_re.search(name):
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
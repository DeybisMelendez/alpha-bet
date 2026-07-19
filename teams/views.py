from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from forecasts.engine import (
    attack_defense_ratings,
    recent_finished_matches,
    upcoming_matches_for_team,
)
from matches.models import Match
from teams.models import Competition, Team, TeamCompetition
from elo.models import EloLog


def _available_seasons(competition_code=None):
    """Temporadas con vínculos TeamCompetition o partidos, ordenadas desc.

    Opcionalmente acota por competición (cuando se filtra el listado).
    """
    tc_qs = TeamCompetition.objects
    if competition_code:
        tc_qs = tc_qs.filter(competition__code=competition_code)
    tc_seasons = set(tc_qs.values_list("season", flat=True).distinct())

    match_qs = Match.objects
    if competition_code:
        match_qs = match_qs.filter(competition__code=competition_code)
    match_seasons = set(
        match_qs.exclude(season="").values_list("season", flat=True).distinct()
    )

    return sorted(tc_seasons | match_seasons, reverse=True)


def _available_countries():
    """Países distintos con equipos, ordenados alfabéticamente."""
    return list(
        Team.objects
        .exclude(country="")
        .values_list("country", flat=True)
        .distinct()
        .order_by("country")
    )


def _available_competitions():
    """Competiciones que tienen vínculo TeamCompetition, ordenadas."""
    return list(
        Competition.objects
        .filter(team_links__isnull=False)
        .distinct()
        .order_by("name")
        .values_list("code", "name")
    )


def competition_list(request):
    """Listado de todas las competiciones disponibles."""
    competitions = (
        Competition.objects
        .prefetch_related("team_links")
        .order_by("name")
    )
    return render(
        request,
        "teams/competition_list.html",
        {"competitions": competitions},
    )


def competition_detail(request, code, season=None):
    """Ranking Elo de equipos de una competición, opcionalmente por temporada."""
    competition = get_object_or_404(Competition, code=code)

    if season is None:
        season = competition.current_season

    available_seasons = _available_seasons(competition)

    team_ids = TeamCompetition.objects.filter(
        competition=competition,
        season=season,
    ).values_list("team_id", flat=True)

    teams = (
        Team.objects.filter(id__in=team_ids)
        .order_by("-elo")
    )

    now = timezone.now()
    upcoming = (
        Match.objects.filter(
            competition=competition,
            season=season,
            status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
            utc_date__gte=now,
        )
        .select_related("home_team", "away_team")
        .order_by("utc_date")[:10]
    )

    recent = (
        Match.objects.filter(
            competition=competition,
            season=season,
            status=Match.Status.FINISHED,
        )
        .select_related("home_team", "away_team")
        .order_by("-utc_date")[:10]
    )

    return render(
        request,
        "teams/competition_detail.html",
        {
            "competition": competition,
            "season": season,
            "available_seasons": available_seasons,
            "teams": teams,
            "upcoming": upcoming,
            "recent": recent,
        },
    )


def team_list(request):
    """Ranking global de equipos filtrable.

    Filtros soportados (todos opcionales vía GET):

    - q:substring en name o tla.
    - competition:código de competición (filtra vía TeamCompetition).
    - season:string de temporada (requiere competition para tener sentido,
      pero se permite suelta).
    - country:país exacto.
    - min_elo / max_elo:rango Elo inclusivo.

    El orden sigue siendo por -elo, name (ranking global).
    """
    q = request.GET.get("q", "").strip()
    competition_code = request.GET.get("competition", "").strip()
    season = request.GET.get("season", "").strip()
    country = request.GET.get("country", "").strip()
    min_elo = request.GET.get("min_elo", "").strip()
    max_elo = request.GET.get("max_elo", "").strip()

    teams = Team.objects.all()

    if q:
        teams = teams.filter(Q(name__icontains=q) | Q(tla__icontains=q))
    if competition_code or season:
        tc_qs = TeamCompetition.objects
        if competition_code:
            tc_qs = tc_qs.filter(competition__code=competition_code)
        if season:
            tc_qs = tc_qs.filter(season=season)
        team_ids = tc_qs.values_list("team_id", flat=True)
        teams = teams.filter(id__in=team_ids)
    if country:
        teams = teams.filter(country=country)
    if min_elo:
        try:
            teams = teams.filter(elo__gte=float(min_elo))
        except ValueError:
            pass
    if max_elo:
        try:
            teams = teams.filter(elo__lte=float(max_elo))
        except ValueError:
            pass

    teams = teams.order_by("-elo", "name")

    context = {
        "teams": teams,
        "q": q,
        "competitions": _available_competitions(),
        "seasons": _available_seasons(competition_code),
        "countries": _available_countries(),
        "selected_competition": competition_code,
        "selected_season": season,
        "selected_country": country,
        "selected_min_elo": min_elo,
        "selected_max_elo": max_elo,
    }
    return render(
        request,
        "teams/team_list.html",
        context,
    )


def _form_label(team, match):
    """Etiqueta W/D/L para el equipo en un partido finalizado."""
    gf = match.home_goals if team == match.home_team else match.away_goals
    ga = match.away_goals if team == match.home_team else match.home_goals
    if gf is None or ga is None:
        return "-"
    if gf > ga:
        return "W"
    if gf < ga:
        return "L"
    return "D"


def _team_neighbors(team):
    """Devuelve (prev, next) por orden de Elo global.

    "Anterior" = equipo inmediatamente peor en Elo (elo < team.elo,
    ordenado desc y .first()).
    "Siguiente" = equipo inmediatamente mejor (elo > team.elo,
    ordenado asc y .first()).
    Coincide con la navegación natural del ranking por Elo.
    """
    prev_team = (
        Team.objects
        .filter(elo__lt=team.elo)
        .exclude(pk=team.pk)
        .order_by("-elo", "name")
        .first()
    )
    next_team = (
        Team.objects
        .filter(elo__gt=team.elo)
        .exclude(pk=team.pk)
        .order_by("elo", "name")
        .first()
    )
    return prev_team, next_team


def team_detail(request, pk):
    """Información completa de un equipo."""
    team = get_object_or_404(Team, pk=pk)

    recent_matches = list(recent_finished_matches(team, n=5))
    upcoming_matches = upcoming_matches_for_team(team)

    atk_home, atk_away, def_home, def_away = attack_defense_ratings(team)
    attack_rating = (atk_home + atk_away) / 2
    defense_rating = (def_home + def_away) / 2

    form_labels = [_form_label(team, m) for m in recent_matches]

    competitions = TeamCompetition.objects.filter(
        team=team,
    ).select_related("competition").order_by("-season", "competition__name")

    elo_logs = (
        EloLog.objects.filter(team=team)
        .select_related("match", "match__home_team", "match__away_team")
        .order_by("-created_at")[:10]
    )

    prev_team, next_team = _team_neighbors(team)

    return render(
        request,
        "teams/team_detail.html",
        {
            "team": team,
            "recent_matches": recent_matches,
            "upcoming_matches": upcoming_matches,
            "attack_rating": attack_rating,
            "defense_rating": defense_rating,
            "atk_home": atk_home,
            "atk_away": atk_away,
            "def_home": def_home,
            "def_away": def_away,
            "form_labels": form_labels,
            "competitions": competitions,
            "elo_logs": elo_logs,
            "prev_team": prev_team,
            "next_team": next_team,
        },
    )
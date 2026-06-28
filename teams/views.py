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


def competition_detail(request, code):
    """Ranking Elo de equipos de una competición en su temporada actual."""
    competition = get_object_or_404(Competition, code=code)
    season = competition.current_season

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
            status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
            utc_date__gte=now,
        )
        .select_related("home_team", "away_team")
        .order_by("utc_date")[:10]
    )

    recent = (
        Match.objects.filter(
            competition=competition,
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
            "teams": teams,
            "upcoming": upcoming,
            "recent": recent,
        },
    )


def team_list(request):
    """Ranking global de equipos ordenado por Elo."""
    q = request.GET.get("q", "").strip()
    teams = Team.objects.all()
    if q:
        teams = teams.filter(
            Q(name__icontains=q)
            | Q(tla__icontains=q)
        )
    teams = teams.order_by("-elo", "name")
    return render(
        request,
        "teams/team_list.html",
        {"teams": teams, "q": q},
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


def team_detail(request, pk):
    """Información completa de un equipo."""
    team = get_object_or_404(Team, pk=pk)

    recent_matches = list(recent_finished_matches(team, n=5))
    upcoming_matches = upcoming_matches_for_team(team)

    attack_rating, defense_rating = attack_defense_ratings(team)

    form_labels = [_form_label(team, m) for m in recent_matches]

    competitions = TeamCompetition.objects.filter(
        team=team,
    ).select_related("competition").order_by("-season", "competition__name")

    elo_logs = (
        EloLog.objects.filter(team=team)
        .select_related("match", "match__home_team", "match__away_team")
        .order_by("-created_at")[:10]
    )

    return render(
        request,
        "teams/team_detail.html",
        {
            "team": team,
            "recent_matches": recent_matches,
            "upcoming_matches": upcoming_matches,
            "attack_rating": attack_rating,
            "defense_rating": defense_rating,
            "form_labels": form_labels,
            "competitions": competitions,
            "elo_logs": elo_logs,
        },
    )
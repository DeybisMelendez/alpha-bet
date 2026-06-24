from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from elo.models import EloLog
from matches.models import Match
from teams.models import Competition


def match_list(request):
    """Listado de partidos filtrables por competición y estado."""
    qs = Match.objects.select_related(
        "competition", "home_team", "away_team"
    )

    competition_code = request.GET.get("competition", "").strip()
    status = request.GET.get("status", "").strip()

    if competition_code:
        qs = qs.filter(competition__code=competition_code)
    if status:
        qs = qs.filter(status=status)

    qs = qs.order_by("-utc_date")
    matches = qs[:100]

    competitions = Competition.objects.all().order_by("name")
    status_choices = Match.Status.choices

    return render(
        request,
        "matches/match_list.html",
        {
            "matches": matches,
            "competitions": competitions,
            "status_choices": status_choices,
            "selected_competition": competition_code,
            "selected_status": status,
        },
    )


def match_detail(request, pk):
    """Detalle de un partido con resultado, Elo y pronóstico asociado."""
    match = get_object_or_404(
        Match.objects.select_related(
            "competition", "home_team", "away_team", "forecast"
        ),
        pk=pk,
    )

    elo_logs = EloLog.objects.filter(match=match).select_related("team")
    return render(
        request,
        "matches/match_detail.html",
        {"match": match, "elo_logs": elo_logs},
    )
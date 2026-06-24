from django.shortcuts import render

from matches.models import Match
from teams.models import Competition, Team


def home(request):
    """Dashboard principal con KPIs y resúmenes rápidos."""
    now = timezone_now()
    competitions_count = Competition.objects.count()
    teams_count = Team.objects.count()
    upcoming_count = Match.objects.filter(
        status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
        utc_date__gte=now,
    ).count()
    finished_today_count = Match.objects.filter(
        status=Match.Status.FINISHED,
        utc_date__date=now.date(),
    ).count()

    top_teams = (
        Team.objects.order_by("-elo")[:5]
    )

    upcoming_matches = (
        Match.objects.filter(
            status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
            utc_date__gte=now,
        )
        .select_related("competition", "home_team", "away_team")
        .order_by("utc_date")[:5]
    )

    latest_forecasts = (
        Match.objects
        .select_related(
            "competition", "home_team", "away_team", "forecast"
        )
        .filter(status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
                forecast__isnull=False)
        .order_by("utc_date")[:5]
    )

    context = {
        "competitions_count": competitions_count,
        "teams_count": teams_count,
        "upcoming_count": upcoming_count,
        "finished_today_count": finished_today_count,
        "top_teams": top_teams,
        "upcoming_matches": upcoming_matches,
        "latest_forecasts": latest_forecasts,
    }
    return render(request, "home.html", context)


def timezone_now():
    """Helper para facilitar pruebas y evitar import circular."""
    from django.utils import timezone
    return timezone.now()
from collections import OrderedDict

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from elo.models import EloLog
from matches.models import Match
from teams.models import Competition

# Filtros de status del listado de partidos.
# - upcoming: programados futuros (SCHEDULED + TIMED).
# - finished: finalizados o adjudicados (pasados).
# - all:sin filtro (respeta rango de fechas si vino).
MATCH_STATUS_CHOICES = (
    ("upcoming", "Próximos"),
    ("finished", "Finalizados"),
    ("all", "Todos"),
)

# Límite del listado. Cohere con FORECAST_LIST_LIMIT de forecasts.
MATCH_LIST_LIMIT = 200


def _parse_date(value):
    """Parsea YYYY-MM-DD devolviendo date o None si está vacío/inválido."""
    if not value:
        return None
    try:
        return timezone.datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _available_seasons():
    """Temporadas con partidos, ordenadas descendente."""
    return list(
        Match.objects
        .exclude(season="")
        .values_list("season", flat=True)
        .distinct()
        .order_by("-season")
    )


def _available_matchdays(competition_code=None, season=None):
    """Jornadas (matchday) disponibles, ordenadas ascendente.

    Opcionalmente acota por competición y/o temporada.
    """
    qs = Match.objects.exclude(matchday__isnull=True)
    if competition_code:
        qs = qs.filter(competition__code=competition_code)
    if season:
        qs = qs.filter(season=season)
    return list(
        qs.values_list("matchday", flat=True)
        .distinct()
        .order_by("matchday")
    )


def match_list(request):
    """Listado de partidos filtrable y agrupado por día.

    Filtros soportados (todos opcionales vía GET):

    - status:upcoming (default) | finished | all.
    - competition:código de competición (eq. PL).
    - season:string de temporada (eq. 2024).
    - matchday:int (jornada).
    - team:int (pk del equipo; filtra local O visitante).
    - date:YYYY-MM-DD (solo partidos de ese día).
    - from / to:YYYY-MM-DD (rango inclusivo por fecha local).

    La agrupación por día se construye en Python (OrderedDict) para
    conservar el orden de la query sin depender de regroup en template.
    """
    today = timezone.localdate()

    status = request.GET.get("status", "upcoming").strip() or "upcoming"
    if status not in dict(MATCH_STATUS_CHOICES):
        status = "upcoming"
    competition_code = request.GET.get("competition", "").strip()
    season = request.GET.get("season", "").strip()
    matchday = request.GET.get("matchday", "").strip()
    team_value = request.GET.get("team", "").strip()
    date_value = request.GET.get("date", "").strip()
    from_value = request.GET.get("from", "").strip()
    to_value = request.GET.get("to", "").strip()

    qs = Match.objects.select_related(
        "competition", "home_team", "away_team", "forecast"
    )

    if status == "upcoming":
        qs = qs.filter(
            status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
            utc_date__date__gte=today,
        )
        qs = qs.order_by("utc_date")
    elif status == "finished":
        qs = qs.filter(status__in=[Match.Status.FINISHED, Match.Status.AWARDED])
        qs = qs.order_by("-utc_date")
    else:  # all
        qs = qs.order_by("utc_date")

    if competition_code:
        qs = qs.filter(competition__code=competition_code)
    if season:
        qs = qs.filter(season=season)
    if matchday:
        try:
            qs = qs.filter(matchday=int(matchday))
        except ValueError:
            pass
    if team_value:
        try:
            team_id = int(team_value)
            qs = qs.filter(
                Q(home_team_id=team_id) | Q(away_team_id=team_id)
            )
        except ValueError:
            pass

    date_d = _parse_date(date_value)
    if date_d:
        qs = qs.filter(utc_date__date=date_d)
    from_d = _parse_date(from_value)
    if from_d:
        qs = qs.filter(utc_date__date__gte=from_d)
    to_d = _parse_date(to_value)
    if to_d:
        qs = qs.filter(utc_date__date__lte=to_d)

    matches = list(qs[:MATCH_LIST_LIMIT])

    matches_grouped = OrderedDict()
    for m in matches:
        day = timezone.localtime(m.utc_date).date()
        matches_grouped.setdefault(day, []).append(m)

    competitions = list(
        Competition.objects.order_by("name").values_list("code", "name")
    )

    context = {
        "matches": matches,
        "matches_grouped": matches_grouped,
        "competitions": competitions,
        "seasons": _available_seasons(),
        "matchdays": _available_matchdays(competition_code, season),
        "status_choices": MATCH_STATUS_CHOICES,
        "selected_status": status,
        "selected_competition": competition_code,
        "selected_season": season,
        "selected_matchday": matchday,
        "selected_team": team_value,
        "selected_date": date_value,
        "selected_from": from_value,
        "selected_to": to_value,
    }
    return render(
        request,
        "matches/match_list.html",
        context,
    )


def _match_neighbors(match):
    """Devuelve (prev, next) por orden cronológico global.

    "Anterior" = partido más cercano ANTES en fecha.
    "Siguiente" = partido más cercano DESPUÉS en fecha.
    Navegación global sin restringir por competición.
    """
    base_qs = Match.objects.exclude(pk=match.pk).select_related(
        "competition", "home_team", "away_team"
    )
    prev_match = (
        base_qs
        .filter(utc_date__lt=match.utc_date)
        .order_by("-utc_date")
        .first()
    )
    next_match = (
        base_qs
        .filter(utc_date__gt=match.utc_date)
        .order_by("utc_date")
        .first()
    )
    return prev_match, next_match


def match_detail(request, pk):
    """Detalle de un partido con resultado, Elo y pronóstico asociado."""
    match = get_object_or_404(
        Match.objects.select_related(
            "competition", "home_team", "away_team", "forecast"
        ),
        pk=pk,
    )

    elo_logs = EloLog.objects.filter(match=match).select_related("team")

    prev_match, next_match = _match_neighbors(match)

    return render(
        request,
        "matches/match_detail.html",
        {
            "match": match,
            "elo_logs": elo_logs,
            "prev_match": prev_match,
            "next_match": next_match,
        },
    )
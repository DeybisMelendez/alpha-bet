from collections import OrderedDict
from itertools import groupby

from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from forecasts.engine import (
    build_matrix,
    expected_goals_from_ratings,
    market_probabilities,
    probabilities_1x2,
    recent_finished_matches,
    top_correct_scores,
)
from forecasts.forms import ForecastCalculateForm
from forecasts.models import Forecast
from matches.models import Match
from teams.models import Competition

# Filtros de status del listado de pronósticos.
# - upcoming:.programados con hora confirmada o pendientes de fecha (futuros).
# - finished:partidos finalizados o adjudicados (passados, para auditar).
# - all:sin filtro de status (respeta rango de fechas si vino).
FORECAST_STATUS_CHOICES = (
    ("upcoming", "Próximos"),
    ("finished", "Finalizados"),
    ("all", "Todos"),
)

# Límite del listado. Suficiente para una ventana semanal/mensual sin
# paginación real; si crece se añadirá Paginator.
FORECAST_LIST_LIMIT = 200


def _build_matrix_context(xg_home, xg_away):
    """Construye el contexto de presentación de la matriz Poisson.

    Devuelve probs 1X2, la celda más probable y la estructura de filas
    lista para el template. Se reutiliza en el detalle de un pronóstico
    persistido y en el cálculo manual.
    """
    matrix = build_matrix(xg_home, xg_away)
    p_home, p_draw, p_away = probabilities_1x2(matrix)
    markets = market_probabilities(matrix)
    top_scores = top_correct_scores(matrix, n=5)
    top_scores_sum_5 = sum(s["prob"] for s in top_scores)

    max_goals = settings.POISSON_MAX_GOALS
    goal_range = list(range(max_goals + 1))

    top_i, top_j, top_p = 0, 0, 0.0
    for i, row in enumerate(matrix):
        for j, p in enumerate(row):
            if p > top_p:
                top_p = p
                top_i, top_j = i, j

    matrix_rows = []
    for i, row in enumerate(matrix):
        cells = []
        row_sum = 0.0
        for j, p in enumerate(row):
            row_sum += p
            if i == top_i and j == top_j:
                kind = "top"
            elif i > j:
                kind = "home"
            elif i == j:
                kind = "draw"
            else:
                kind = "away"
            cells.append({"j": j, "p": p, "kind": kind})
        matrix_rows.append({"i": i, "cells": cells, "row_sum": row_sum})

    return {
        "goal_range": goal_range,
        "matrix_rows": matrix_rows,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "markets": markets,
        "top_i": top_i,
        "top_j": top_j,
        "top_prob": top_p,
        "top_scores": top_scores,
        "top_scores_sum_5": top_scores_sum_5,
    }


def _parse_date(value):
    """Parsea YYYY-MM-DD devolviendo date o None si está vacío/inválido."""
    if not value:
        return None
    try:
        return timezone.datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def _available_seasons():
    """Temporadas con pronósticos, ordenadas descendente."""
    return list(
        Forecast.objects
        .values_list("match__season", flat=True)
        .distinct()
        .order_by("-match__season")
    )


def _available_matchdays(competition_code=None, season=None):
    """Jornadas (matchday) disponibles, ordenadas ascendente.

    Opcionalmente acota por competición y/o temporada para no llenar
    el select con jornadas de otras ligas.
    """
    qs = Forecast.objects.exclude(match__matchday__isnull=True)
    if competition_code:
        qs = qs.filter(match__competition__code=competition_code)
    if season:
        qs = qs.filter(match__season=season)
    return list(
        qs.values_list("match__matchday", flat=True)
        .distinct()
        .order_by("match__matchday")
    )


def forecast_list(request):
    """Listado de pronósticos filtrable y agrupado por día.

    Filtros soportados (todos opcionales vía GET):

    - status:upcoming (default) | finished | all.
    - competition:código de competición (eq. PL).
    - season:string de temporada (eq. 2024).
    - matchday:int (jornada de liga).
    - date:YYYY-MM-DD (solo partidos de ese día).
    - from / to:YYYY-MM-DD (rango inclusivo por fecha local).
    - fallback:1 (solo pronósticos fallback).

    La agrupación por día se construye en Python ( OrderedDict ) para
    no depender de regroup en template y conservar el orden de la query.
    """
    today = timezone.localdate()

    status = request.GET.get("status", "upcoming").strip() or "upcoming"
    if status not in dict(FORECAST_STATUS_CHOICES):
        status = "upcoming"
    competition_code = request.GET.get("competition", "").strip()
    season = request.GET.get("season", "").strip()
    matchday = request.GET.get("matchday", "").strip()
    date_value = request.GET.get("date", "").strip()
    from_value = request.GET.get("from", "").strip()
    to_value = request.GET.get("to", "").strip()
    fallback_only = request.GET.get("fallback", "").strip()

    qs = Forecast.objects.select_related(
        "match__competition",
        "match__home_team",
        "match__away_team",
    )

    # Filtro por status. "all" no aplica nada y deja el rango de fechas
    # decidir el alcance (necesario porque ordenar asc/dsc depende).
    if status == "upcoming":
        qs = qs.filter(
            match__status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
            match__utc_date__date__gte=today,
        )
        qs = qs.order_by("match__utc_date")
    elif status == "finished":
        qs = qs.filter(match__status__in=[Match.Status.FINISHED, Match.Status.AWARDED])
        qs = qs.order_by("-match__utc_date")
    else:  # all
        qs = qs.order_by("match__utc_date")

    if competition_code:
        qs = qs.filter(match__competition__code=competition_code)
    if season:
        qs = qs.filter(match__season=season)
    if matchday:
        try:
            qs = qs.filter(match__matchday=int(matchday))
        except ValueError:
            pass

    date_d = _parse_date(date_value)
    if date_d:
        qs = qs.filter(match__utc_date__date=date_d)
    from_d = _parse_date(from_value)
    if from_d:
        qs = qs.filter(match__utc_date__date__gte=from_d)
    to_d = _parse_date(to_value)
    if to_d:
        qs = qs.filter(match__utc_date__date__lte=to_d)

    if fallback_only == "1":
        qs = qs.filter(is_fallback=True)

    forecasts = list(qs[:FORECAST_LIST_LIMIT])

    # Agrupación por día (fecha local del partido).
    forecasts_grouped = OrderedDict()
    for f in forecasts:
        day = timezone.localtime(f.match.utc_date).date()
        forecasts_grouped.setdefault(day, []).append(f)

    competitions = (
        Competition.objects.order_by("name").values_list("code", "name")
    )

    context = {
        "forecasts": forecasts,
        "forecasts_grouped": forecasts_grouped,
        "competitions": list(competitions),
        "seasons": _available_seasons(),
        "matchdays": _available_matchdays(competition_code, season),
        "status_choices": FORECAST_STATUS_CHOICES,
        "selected_status": status,
        "selected_competition": competition_code,
        "selected_season": season,
        "selected_matchday": matchday,
        "selected_date": date_value,
        "selected_from": from_value,
        "selected_to": to_value,
        "fallback_only": fallback_only,
        "today": today.isoformat(),
    }
    return render(
        request,
        "forecasts/forecast_list.html",
        context,
    )


def _recent_matches_for_team(team, n=5):
    """Lista de últimos n partidos finalizados de un equipo."""
    matches = recent_finished_matches(team, n=n)
    return [{
        "date": m.utc_date,
        "home_team": m.home_team,
        "away_team": m.away_team,
        "home_goals": m.home_goals,
        "away_goals": m.away_goals,
        "competition": m.competition,
    } for m in matches]


def _forecast_neighbors(forecast):
    """Devuelve (prev, next) por orden cronológico global.

    "Anterior" = pronóstico del partido más cercano ANTES en fecha.
    "Siguiente" = pronóstico del partido más cercano DESPUÉS en fecha.

    Solo considera otros Forecast existentes (no importa la competición
    ni el estado), como el usuario decidió en el plan.
    """
    base_qs = Forecast.objects.exclude(pk=forecast.pk).select_related(
        "match__competition",
        "match__home_team",
        "match__away_team",
    )
    prev_forecast = (
        base_qs
        .filter(match__utc_date__lt=forecast.match.utc_date)
        .order_by("-match__utc_date")
        .first()
    )
    next_forecast = (
        base_qs
        .filter(match__utc_date__gt=forecast.match.utc_date)
        .order_by("match__utc_date")
        .first()
    )
    return prev_forecast, next_forecast


def forecast_detail(request, pk):
    """Detalle del pronóstico: xG, matrix Poisson, probs 1X2, forma y
    últimos 5 partidos de cada equipo.
    """
    forecast = get_object_or_404(
        Forecast.objects.select_related(
            "match__competition",
            "match__home_team",
            "match__away_team",
        ),
        pk=pk,
    )

    matrix_ctx = _build_matrix_context(forecast.xg_home, forecast.xg_away)

    recent_home = _recent_matches_for_team(forecast.match.home_team, n=5)
    recent_away = _recent_matches_for_team(forecast.match.away_team, n=5)

    prev_forecast, next_forecast = _forecast_neighbors(forecast)

    context = {
        "forecast": forecast,
        "recent_home": recent_home,
        "recent_away": recent_away,
        "prev_forecast": prev_forecast,
        "next_forecast": next_forecast,
        **matrix_ctx,
    }
    return render(request, "forecasts/forecast_detail.html", context)


def forecast_calculate(request):
    """Cálculo manual de pronóstico a partir de ratings ingresados.

    No persiste nada: solo calcula y muestra el resultado. Útil para
    escenarios what-if y probar el modelo sin un partido en la DB.

    Soporta sede neutral (anula localía) y factores de forma reciente
    (multiplicativos sobre λ).
    """
    if request.method == "POST":
        form = ForecastCalculateForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            xg_home, xg_away = expected_goals_from_ratings(
                cd["home_elo"],
                cd["home_attack"],
                cd["home_defense"],
                cd["away_elo"],
                cd["away_attack"],
                cd["away_defense"],
                home_advantage=cd["home_advantage"],
                is_neutral=cd["is_neutral"],
                form_home=cd["form_home"],
                form_away=cd["form_away"],
            )
            matrix_ctx = _build_matrix_context(xg_home, xg_away)

            context = {
                "form": form,
                "xg_home": xg_home,
                "xg_away": xg_away,
                "calculated": True,
                **matrix_ctx,
            }
            return render(
                request,
                "forecasts/forecast_calculate.html",
                context,
            )
    else:
        form = ForecastCalculateForm()

    return render(
        request,
        "forecasts/forecast_calculate.html",
        {"form": form, "calculated": False},
    )
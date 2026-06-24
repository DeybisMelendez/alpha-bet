from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from forecasts.engine import (
    build_matrix,
    expected_goals_from_ratings,
    probabilities_1x2,
    value_bet_analysis,
)
from forecasts.forms import ForecastCalculateForm, ValueBetForm
from forecasts.models import Forecast
from matches.models import Match


def _build_matrix_context(xg_home, xg_away):
    """Construye el contexto de presentación de la matriz Poisson.

    Devuelve probs 1X2, la celda más probable y la estructura de filas
    lista para el template. Se reutiliza en el detalle de un pronóstico
    persistido y en el cálculo manual.
    """
    matrix = build_matrix(xg_home, xg_away)
    p_home, p_draw, p_away = probabilities_1x2(matrix)

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
        "top_i": top_i,
        "top_j": top_j,
        "top_prob": top_p,
    }


def forecast_list(request):
    """Listado de pronósticos de partidos próximos (programados)."""
    now = timezone.now()
    qs = (
        Forecast.objects
        .select_related(
            "match__competition",
            "match__home_team",
            "match__away_team",
        )
        .filter(
            match__status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
            match__utc_date__gte=now,
        )
        .order_by("match__utc_date")
    )
    fallback_only = request.GET.get("fallback", "").strip()
    if fallback_only == "1":
        qs = qs.filter(is_fallback=True)

    forecasts = qs[:100]
    return render(
        request,
        "forecasts/forecast_list.html",
        {"forecasts": forecasts, "fallback_only": fallback_only},
    )


def forecast_detail(request, pk):
    """Detalle del pronóstico: xG, matrix Poisson, probs 1X2 y forma.

    Acepta POST con cuotas 1X2 (ValueBetForm) para analizar value bet al
    vuelo. Las cuotas no se persisten: el análisis es solo para este partido.
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

    value_analysis = None
    if request.method == "POST":
        value_form = ValueBetForm(request.POST)
        if value_form.is_valid():
            cd = value_form.cleaned_data
            if cd.get("odd_home") is not None:
                value_analysis = value_bet_analysis(
                    forecast.prob_home_win,
                    forecast.prob_draw,
                    forecast.prob_away_win,
                    cd["odd_home"],
                    cd["odd_draw"],
                    cd["odd_away"],
                )
    else:
        value_form = ValueBetForm()

    context = {
        "forecast": forecast,
        "value_form": value_form,
        "value_analysis": value_analysis,
        **matrix_ctx,
    }
    return render(request, "forecasts/forecast_detail.html", context)


def forecast_calculate(request):
    """Cálculo manual de pronóstico a partir de ratings ingresados.

    No persiste nada: solo calcula y muestra el resultado. Útil para
    escenarios what-if y probar el modelo sin un partido en la DB.
    """
    if request.method == "POST":
        form = ForecastCalculateForm(request.POST)
        if form.is_valid():
            xg_home, xg_away = expected_goals_from_ratings(
                form.cleaned_data["home_elo"],
                form.cleaned_data["home_attack"],
                form.cleaned_data["home_defense"],
                form.cleaned_data["away_elo"],
                form.cleaned_data["away_attack"],
                form.cleaned_data["away_defense"],
                home_advantage=form.cleaned_data["home_advantage"],
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
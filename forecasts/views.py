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

    context = {
        "forecast": forecast,
        "recent_home": recent_home,
        "recent_away": recent_away,
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
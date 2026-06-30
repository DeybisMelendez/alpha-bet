from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from forecasts.engine import (
    build_matrix,
    expected_goals_from_ratings,
    market_probabilities,
    probabilities_1x2,
    value_bet_analysis,
)
from forecasts.forms import ForecastCalculateForm, ValueBetForm
from forecasts.models import Forecast, MarketForecast
from matches.models import Match
from collections import OrderedDict


def _secondary_markets(forecast):
    """Agrupa los MarketForecast del pronóstico por mercado (label)."""
    groups = OrderedDict()
    for mf in forecast.markets.all().order_by("market", "selection"):
        groups.setdefault(mf.get_market_display(), []).append(mf)
    return groups


def _build_matrix_context(xg_home, xg_away):
    """Construye el contexto de presentación de la matriz Poisson.

    Devuelve probs 1X2, la celda más probable y la estructura de filas
    lista para el template. Se reutiliza en el detalle de un pronóstico
    persistido y en el cálculo manual.
    """
    matrix = build_matrix(xg_home, xg_away)
    p_home, p_draw, p_away = probabilities_1x2(matrix)
    markets = market_probabilities(matrix)

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
    secondary_by_market = _secondary_markets(forecast)

    value_analysis = None
    if request.method == "POST":
        value_form = ValueBetForm(request.POST)
        if value_form.is_valid():
            cd = value_form.cleaned_data
            odds = {
                "home": cd.get("odd_home"),
                "draw": cd.get("odd_draw"),
                "away": cd.get("odd_away"),
                "1x": cd.get("odd_1x"),
                "x2": cd.get("odd_x2"),
                "12": cd.get("odd_12"),
                "btts": cd.get("odd_btts"),
                "score_home": cd.get("odd_score_home"),
                "score_away": cd.get("odd_score_away"),
                "over_05": cd.get("odd_over_05"),
                "over_15": cd.get("odd_over_15"),
                "over_25": cd.get("odd_over_25"),
                "over_35": cd.get("odd_over_35"),
                "over_45": cd.get("odd_over_45"),
                "dnb_home": cd.get("odd_dnb_home"),
                "dnb_away": cd.get("odd_dnb_away"),
            }
            if any(o is not None for o in odds.values()):
                value_analysis = value_bet_analysis(matrix_ctx["markets"], odds)
    else:
        value_form = ValueBetForm()

    context = {
        "forecast": forecast,
        "value_form": value_form,
        "value_analysis": value_analysis,
        "secondary_by_market": secondary_by_market,
        **matrix_ctx,
    }
    return render(request, "forecasts/forecast_detail.html", context)


def forecast_calculate(request):
    """Cálculo manual de pronóstico a partir de ratings ingresados.

    No persiste nada: solo calcula y muestra el resultado. Útil para
    escenarios what-if y probar el modelo sin un partido en la DB.

    Soporta sede neutral (anula localía) y factores de forma reciente
    (multiplicativos sobre λ). Tras calcular, opcionalmente analiza
    value bet contra cuotas ingresadas (ValueBetForm), igual que la
    view de detalle.
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

            # Análisis de value bet opcional (cuotas en el mismo POST).
            value_form = ValueBetForm(request.POST)
            value_analysis = None
            if value_form.is_valid():
                vcd = value_form.cleaned_data
                odds = {
                    "home": vcd.get("odd_home"),
                    "draw": vcd.get("odd_draw"),
                    "away": vcd.get("odd_away"),
                    "1x": vcd.get("odd_1x"),
                    "x2": vcd.get("odd_x2"),
                    "12": vcd.get("odd_12"),
"btts": vcd.get("odd_btts"),
                "score_home": vcd.get("odd_score_home"),
                "score_away": vcd.get("odd_score_away"),
                "over_05": vcd.get("odd_over_05"),
                    "over_15": vcd.get("odd_over_15"),
                    "over_25": vcd.get("odd_over_25"),
                    "over_35": vcd.get("odd_over_35"),
                    "over_45": vcd.get("odd_over_45"),
                    "dnb_home": vcd.get("odd_dnb_home"),
                    "dnb_away": vcd.get("odd_dnb_away"),
                }
                if any(o is not None for o in odds.values()):
                    value_analysis = value_bet_analysis(
                        matrix_ctx["markets"], odds
                    )
            else:
                value_form = ValueBetForm()

            context = {
                "form": form,
                "value_form": value_form,
                "value_analysis": value_analysis,
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
        value_form = ValueBetForm()

    return render(
        request,
        "forecasts/forecast_calculate.html",
        {"form": form, "value_form": ValueBetForm(), "calculated": False},
    )
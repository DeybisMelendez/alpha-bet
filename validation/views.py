from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from teams.models import Competition
from validation.models import CalibrationBin, ForecastEvaluation
from validation.selectors import available_seasons
from validation.services import aggregate_kpis

# Temporadas por defecto al cargar la página (año actual).
_DEFAULT_DAYS_BACK = 365


def _parse_date(value):
    if not value:
        return None
    try:
        return timezone.datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def validation_report(request):
    """Reporte de validación: KPIs agregados + tabla de calibración.

    Filtros GET opcionales: from, to, season, competition.
    Por defecto cubre los últimos 365 días.
    """
    today = timezone.localdate()

    from_value = request.GET.get("from", "").strip()
    to_value = request.GET.get("to", "").strip()
    season = request.GET.get("season", "").strip()
    competition_code = request.GET.get("competition", "").strip()

    from_d = _parse_date(from_value) or (
        today - timezone.timedelta(days=_DEFAULT_DAYS_BACK)
    )
    to_d = _parse_date(to_value) or today

    qs = ForecastEvaluation.objects.select_related(
        "match__competition", "match__home_team", "match__away_team"
    ).filter(
        match__utc_date__date__gte=from_d,
        match__utc_date__date__lte=to_d,
    )
    if season:
        qs = qs.filter(season=season)
    if competition_code:
        qs = qs.filter(competition__code=competition_code)

    kpis = aggregate_kpis(qs)

    # Distribución de outcomes reales (para inspección rápida de balance).
    outcome_dist = list(
        qs.values("actual_outcome").annotate(n=Count("id")).order_by("actual_outcome")
    )
    total_evaluated = kpis["n"]

    # Bins de calibración: el snapshot es único y global (cada refresh del
    # comando evaluate_forecasts reemplaza la tabla entera). Mostramos lo
    # que haya, etiquetado por la propia ventana del snapshot.
    bins_qs = CalibrationBin.objects.all().order_by("market", "bin_start")
    bins_qs = CalibrationBin.objects.all().order_by("market", "bin_start")
    if bins_qs.exists():
        # Etiqueta informativa con la ventana del snapshot disponible.
        first = bins_qs.first()
        bins_window_from = first.window_from
        bins_window_to = first.window_to
    else:
        bins_window_from = bins_window_to = None

    # Precompute rows structure for template: lista de (label, bin_rows)
    # donde cada row ya trae el gap (predicho - observado) calculado.
    raw_by_market = {}
    for b in bins_qs:
        raw_by_market.setdefault(b.market, []).append(b)

    market_labels = dict(CalibrationBin.Market.choices)
    bins_groups = []
    for market_code, _label in CalibrationBin.Market.choices:
        bins = raw_by_market.get(market_code, [])
        rows = []
        for b in bins:
            gap = (b.predicted_avg - b.observed_freq) if b.count else None
            rows.append(
                {
                    "bin_start": b.bin_start,
                    "bin_end": b.bin_end,
                    "count": b.count,
                    "predicted_avg": b.predicted_avg,
                    "observed_freq": b.observed_freq,
                    "gap": gap,
                }
            )
        bins_groups.append(
            {
                "code": market_code,
                "label": market_labels.get(market_code, market_code),
                "rows": rows,
            }
        )

    competitions = list(
        Competition.objects.order_by("name").values_list("code", "name")
    )

    context = {
        "kpis": kpis,
        "outcome_dist": outcome_dist,
        "total_evaluated": total_evaluated,
        "bins_groups": bins_groups,
        "bins_window_from": bins_window_from,
        "bins_window_to": bins_window_to,
        "competitions": competitions,
        "seasons": available_seasons(),
        "selected_from": from_d.isoformat(),
        "selected_to": to_d.isoformat(),
        "selected_season": season,
        "selected_competition": competition_code,
        "today": today.isoformat(),
    }
    return render(request, "validation/report.html", context)

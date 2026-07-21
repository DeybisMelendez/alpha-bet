from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from teams.models import Competition
from validation.models import CalibrationBin, CalibrationSnapshot, ForecastEvaluation
from validation.selectors import available_seasons, last_snapshot
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


def _bins_groups_for_snapshot(snapshot):
    """Construye la estructura de bins por mercado para el template.

    Devuelve una lista de dicts {code, label, rows} donde cada row ya
    trae el gap (predicho − observado) calculado. Vacío si el snapshot
    no tiene bins (ej. recién creado sin datos).
    """
    raw_by_market = {}
    if snapshot is not None:
        for b in snapshot.bins.all().order_by("market", "bin_start"):
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
    return bins_groups


def validation_report(request):
    """Reporte de validación: KPIs agregados + tabla de calibración.

    Filtros GET opcionales: from, to, season, competition.
    Por defecto cubre los últimos 365 días.

    Los KPIs agregan solo las ForecastEvaluation del rango filtrado; la
    calibración mostrada es la del último CalibrationSnapshot disponible
    (no se recalcula por rango — ver /validation/evolution/ para explorar
    snapshots históricos).
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

    # Bins del último snapshot vigente (la calibración no se recalcula
    # por rango; para histórico está /validation/evolution/).
    snapshot = last_snapshot()
    if snapshot is not None:
        # Prefetch bins para evitar N+1 al iterar por mercado.
        snapshot = (
            CalibrationSnapshot.objects.prefetch_related("bins")
            .select_related("competition")
            .get(pk=snapshot.pk)
        )
        bins_window_from = snapshot.window_from
        bins_window_to = snapshot.window_to
        bins_snapshot_at = snapshot.snapshot_at
    else:
        bins_window_from = bins_window_to = bins_snapshot_at = None
    bins_groups = _bins_groups_for_snapshot(snapshot)

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
        "bins_snapshot_at": bins_snapshot_at,
        "bins_snapshot_id": snapshot.id if snapshot else None,
        "bins_snapshot_trigger": snapshot.trigger if snapshot else None,
        "snapshots_count": CalibrationSnapshot.objects.count(),
        "competitions": competitions,
        "seasons": available_seasons(),
        "selected_from": from_d.isoformat(),
        "selected_to": to_d.isoformat(),
        "selected_season": season,
        "selected_competition": competition_code,
        "today": today.isoformat(),
    }
    return render(request, "validation/report.html", context)


def evolution(request):
    """Vista de evolución histórica del modelo.

    Muestra una serie temporal de KPIs agregados por snapshot (Log Loss,
    Brier, RPS, MAE de λ, top_score_hit_ratio) y la evolución del gap
    por bin de probabilidad para un mercado seleccionable. Tabla de
    snapshots con enlace a detalle.

    Filtros GET opcionales: from, to (rango sobre snapshot_at),
    snapshot (id del snapshot a inspeccionar en detalle),
    gap_market (mercado para el gráfico de gaps).
    """
    from validation.selectors import snapshots_in_range

    today = timezone.localdate()

    from_value = request.GET.get("from", "").strip()
    to_value = request.GET.get("to", "").strip()
    snapshot_id = request.GET.get("snapshot", "").strip()
    gap_market_code = request.GET.get("gap_market", CalibrationBin.Market.HOME_WIN).strip()

    # Default: últimos 365 días de snapshots.
    from_d = _parse_date(from_value) or (
        today - timezone.timedelta(days=_DEFAULT_DAYS_BACK)
    )
    to_d = _parse_date(to_value) or today

    snapshots = snapshots_in_range(from_d, to_d)
    snapshots_list = list(snapshots)

    # KPI series para Chart.js: una lista de {x, log_loss, brier, ...}.
    # Mantenemos ascendente por snapshot_at.
    kpi_series = [
        {
            "x": s.snapshot_at.isoformat(),
            "label": s.snapshot_at.strftime("%Y-%m-%d %H:%M"),
            "id": s.id,
            "n": s.n,
            "log_loss_1x2": s.log_loss_1x2,
            "brier_1x2": s.brier_1x2,
            "rps_1x2": s.rps_1x2,
            "ae_xg_home": s.ae_xg_home,
            "ae_xg_away": s.ae_xg_away,
            "ae_total": s.ae_total,
            "top_score_hit_ratio": s.top_score_hit_ratio,
            "trigger": s.trigger,
        }
        for s in snapshots_list
    ]

    # Gap series: para el mercado seleccionado, una línea por bin (0..9)
    # con el gap = predicted_avg − observed_freq en cada snapshot.
    gap_series = _build_gap_series(snapshots_list, gap_market_code)

    # Snapshot detallado: parámetro ?snapshot=<id>, default el último.
    if snapshot_id:
        detailed = get_object_or_404(
            CalibrationSnapshot.objects.prefetch_related("bins").select_related(
                "competition"
            ),
            pk=snapshot_id,
        )
    else:
        detailed = snapshots_list[-1] if snapshots_list else None
        if detailed is not None:
            detailed = (
                CalibrationSnapshot.objects.prefetch_related("bins")
                .select_related("competition")
                .get(pk=detailed.pk)
            )

    bins_groups = _bins_groups_for_snapshot(detailed)

    competitions = list(
        Competition.objects.order_by("name").values_list("code", "name")
    )

    trigger_labels = dict(CalibrationSnapshot.Trigger.choices)

    context = {
        "snapshots": snapshots_list,
        "snapshots_count": len(snapshots_list),
        "total_snapshots": CalibrationSnapshot.objects.count(),
        "kpi_series": kpi_series,
        "gap_series": gap_series,
        "gap_market_selected": gap_market_code,
        "markets": CalibrationBin.Market.choices,
        "detailed_snapshot": detailed,
        "detailed_bins_groups": bins_groups,
        "trigger_labels": trigger_labels,
        "competitions": competitions,
        "seasons": available_seasons(),
        "selected_from": from_d.isoformat(),
        "selected_to": to_d.isoformat(),
        "today": today.isoformat(),
    }
    return render(request, "validation/evolution.html", context)


def _build_gap_series(snapshots_list, market_code):
    """Para `market_code`, devuelve [{bin_label, data: [{x, gap}, ...]}, ...].

    Cada `bin_label` es "0..9" según su posición (bin_start = i/10). Solo
    se incluyen bins con count > 0 (bins vacíos arrastran ruido a gap=0).
    """
    series_by_bin = {}
    for snap in snapshots_list:
        for b in snap.bins.filter(market=market_code, count__gt=0):
            label = f"{b.bin_start:.1f}"
            gap = b.predicted_avg - b.observed_freq
            series_by_bin.setdefault(label, []).append(
                {"x": snap.snapshot_at.isoformat(), "gap": round(gap, 4)}
            )
    return [
        {"bin_label": label, "data": points}
        for label, points in sorted(series_by_bin.items())
    ]

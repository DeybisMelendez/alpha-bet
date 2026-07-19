from datetime import datetime

from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from validation.metrics import (
    ae,
    brier_multiclass,
    compute_calibration_rows,
    log_loss,
    outcome_from_match,
    probs_1x2_from_forecast,
    rps_1x2,
    top_score_hit,
)
from validation.models import CalibrationBin, ForecastEvaluation
from validation.selectors import finished_with_forecast_qs


def evaluate_match(match):
    """Crea o actualiza la ForecastEvaluation para un partido finalizado.

    Usa el Forecast ya persistido en match.forecast (no recalcula).
    Idempotente: re-ejecutar sobrescribe con los mismos valores.
    Devuelve (ForecastEvaluation, created_bool) o None si falta algo.
    """
    forecast = getattr(match, "forecast", None)
    if forecast is None or not match.has_result:
        return None

    actual_home = int(match.home_goals)
    actual_away = int(match.away_goals)
    actual = outcome_from_match(actual_home, actual_away, match.status_short)
    probs = probs_1x2_from_forecast(forecast)

    ll = log_loss(probs, actual)
    brier = brier_multiclass(probs, actual)
    rps = rps_1x2(probs, actual)
    ae_home = ae(forecast.xg_home, actual_home)
    ae_away = ae(forecast.xg_away, actual_away)
    ae_total = abs(forecast.xg_home + forecast.xg_away - (actual_home + actual_away))
    hit = top_score_hit(forecast, actual_home, actual_away)

    obj, created = ForecastEvaluation.objects.update_or_create(
        match=match,
        defaults={
            "actual_home_goals": actual_home,
            "actual_away_goals": actual_away,
            "actual_outcome": actual,
            "log_loss_1x2": ll,
            "brier_1x2": brier,
            "rps_1x2": rps,
            "ae_xg_home": ae_home,
            "ae_xg_away": ae_away,
            "ae_total": ae_total,
            "top_score_hit": hit,
            "season": match.season or "",
            "competition": match.competition,
            "is_fallback": bool(forecast.is_fallback),
        },
    )
    return obj, created


def aggregate_kpis(evaluations_qs):
    """KPIs promedio sobre un queryset de ForecastEvaluation.

    Devuelve dict con n, log_loss, brier, rps, ae_xg_home/away/total y
    top_score_hit_ratio. Vacío (n=0) → ceros.
    """
    n = evaluations_qs.count()
    if n == 0:
        return {
            "n": 0,
            "log_loss_1x2": 0.0,
            "brier_1x2": 0.0,
            "rps_1x2": 0.0,
            "ae_xg_home": 0.0,
            "ae_xg_away": 0.0,
            "ae_total": 0.0,
            "top_score_hit_ratio": 0.0,
        }

    a = evaluations_qs.aggregate(
        avg_ll=Avg("log_loss_1x2"),
        avg_brier=Avg("brier_1x2"),
        avg_rps=Avg("rps_1x2"),
        avg_ae_home=Avg("ae_xg_home"),
        avg_ae_away=Avg("ae_xg_away"),
        avg_ae_total=Avg("ae_total"),
        hits=Sum("top_score_hit"),
        total=Count("id"),
    )
    return {
        "n": a["total"] or 0,
        "log_loss_1x2": a["avg_ll"] or 0.0,
        "brier_1x2": a["avg_brier"] or 0.0,
        "rps_1x2": a["avg_rps"] or 0.0,
        "ae_xg_home": a["avg_ae_home"] or 0.0,
        "ae_xg_away": a["avg_ae_away"] or 0.0,
        "ae_total": a["avg_ae_total"] or 0.0,
        "top_score_hit_ratio": (a["hits"] or 0) / (a["total"] or 1),
    }


# Mapea cada outcome de CalibrationBin con un accessor del Forecast.
_MARKET_ACCESSOR = {
    CalibrationBin.Market.HOME_WIN: lambda f: f.prob_home_win,
    CalibrationBin.Market.DRAW: lambda f: f.prob_draw,
    CalibrationBin.Market.AWAY_WIN: lambda f: f.prob_away_win,
}

_OUTCOME_KEYS = {
    CalibrationBin.Market.HOME_WIN: "1",
    CalibrationBin.Market.DRAW: "X",
    CalibrationBin.Market.AWAY_WIN: "2",
}


def _parse_dt(value):
    """Acepta 'YYYY-MM-DD' o date/datetime; otros devuelven None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        from django.utils import timezone

        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    import datetime as _dt

    try:
        d = _dt.datetime.strptime(str(value).strip(), "%Y-%m-%d")
        from django.utils import timezone

        return d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def refresh_calibration_bins(
    date_from=None, date_to=None, season=None, competition_code=None
):
    """Reconstruye los bins de calibración para un rango/filtros.

    Borra los CalibrationBin existentes para esa ventana y los recalcula
    a partir de las ForecastEvaluation. Una sola llamada transaccional
    para evitar dejar tabla a medias.
    """
    qs = finished_with_forecast_qs(
        date_from=date_from,
        date_to=date_to,
        season=season,
        competition_code=competition_code,
    )
    # Acota a partidos con evaluation (debe haberse corrido antes).
    qs = qs.filter(evaluation__isnull=False).select_related("forecast", "evaluation")

    # Bordes temporales para etiquetar los bins (window_from / window_to).
    # Si la ventana está vacía, tomamos el rango solicitado (o ahora) y no
    # dejamos bins viejos colgando: cada refresh reemplaza la table entera
    # (simplificación para tool personal: un único snapshot global vigente).
    if qs.exists():
        window_from = qs.order_by("utc_date").first().utc_date
        window_to = qs.order_by("-utc_date").first().utc_date
    elif date_from or date_to:
        today = timezone.now()
        wf = _parse_dt(date_from) or today
        wt = _parse_dt(date_to) or today
        window_from, window_to = wf, wt
    else:
        window_from = window_to = timezone.now()

    pairs_by_market = {m: [] for m in CalibrationBin.Market}
    for match in qs.iterator():
        fc = match.forecast
        actual = match.evaluation.actual_outcome
        for market, accessor in _MARKET_ACCESSOR.items():
            prob = accessor(fc)
            occurred = actual == _OUTCOME_KEYS[market]
            pairs_by_market[market].append((prob, occurred))

    with transaction.atomic():
        # Mantenemos un único snapshot global vigente (tool personal):
        # cada refresh reemplaza la tabla entera. Si se desea conservar
        # múltiples ventanas simultáneas, cambiar por un filtro exacto
        # window_from/to como antes.
        CalibrationBin.objects.all().delete()
        new_rows = []
        for market, pairs in pairs_by_market.items():
            for row in compute_calibration_rows(pairs):
                new_rows.append(
                    CalibrationBin(
                        market=market,
                        bin_start=row["bin_start"],
                        bin_end=row["bin_end"],
                        count=row["count"],
                        predicted_avg=row["predicted_avg"],
                        observed_freq=row["observed_freq"],
                        window_from=window_from,
                        window_to=window_to,
                    )
                )
        CalibrationBin.objects.bulk_create(new_rows)
    return len(new_rows), window_from, window_to

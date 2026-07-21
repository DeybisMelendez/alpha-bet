from datetime import datetime

from matches.models import Match


def last_snapshot():
    """Devuelve el CalibrationSnapshot más reciente, o None si no hay."""
    from validation.models import CalibrationSnapshot

    return (
        CalibrationSnapshot.objects.select_related("competition")
        .order_by("-snapshot_at")
        .first()
    )


def snapshots_in_range(date_from=None, date_to=None):
    """Snapshots ordenados ascendentemente por snapshot_at.

    Incluye prefetch_related de bins para evitar N+1 al construir las
    series de la vista de evolución. Los bins de cada snapshot vienen
    en ``snapshot.bins.all()``.

    :param date_from/date_to: str 'YYYY-MM-DD' o date (filtro sobre
        snapshot_at, no sobre window_from/to, para incluir snapshots
        hechos en ese periodo).
    """
    from django.db.models import Prefetch
    from validation.models import CalibrationBin, CalibrationSnapshot

    qs = CalibrationSnapshot.objects.select_related("competition").all()
    d_from = _parse_date(date_from)
    if d_from:
        qs = qs.filter(snapshot_at__date__gte=d_from)
    d_to = _parse_date(date_to)
    if d_to:
        qs = qs.filter(snapshot_at__date__lte=d_to)
    bin_qs = CalibrationBin.objects.order_by("market", "bin_start")
    return qs.prefetch_related(Prefetch("bins", queryset=bin_qs)).order_by(
        "snapshot_at"
    )


def finished_with_forecast_qs(
    date_from=None,
    date_to=None,
    season=None,
    competition_code=None,
):
    """Query de partidos finalizados con Forecast existente.

    :param date_from/date_to: str 'YYYY-MM-DD' o date (opcional, inclusivo).
    :param season: string de temporada (eq. '2024').
    :param competition_code: código de competición (eq. 'PL').
    """
    qs = Match.objects.filter(
        status__in=[Match.Status.FINISHED, Match.Status.AWARDED],
        home_goals__isnull=False,
        away_goals__isnull=False,
        forecast__isnull=False,
    ).select_related("forecast", "competition", "home_team", "away_team")
    d_from = _parse_date(date_from)
    if d_from:
        qs = qs.filter(utc_date__date__gte=d_from)
    d_to = _parse_date(date_to)
    if d_to:
        qs = qs.filter(utc_date__date__lte=d_to)
    if season:
        qs = qs.filter(season=season)
    if competition_code:
        qs = qs.filter(competition__code=competition_code)
    return qs


def _parse_date(value):
    """Acepta str 'YYYY-MM-DD' o date/datetime; otros → None."""
    if value is None or value == "":
        return None
    if isinstance(value, (datetime,)):
        return value.date()
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def available_seasons():
    """Temporadas con evaluaciones (descendente)."""
    from validation.models import ForecastEvaluation

    return list(
        ForecastEvaluation.objects.exclude(season="")
        .values_list("season", flat=True)
        .distinct()
        .order_by("-season")
    )

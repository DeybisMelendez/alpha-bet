from datetime import datetime

from matches.models import Match


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

from datetime import datetime

from django.core.management.base import BaseCommand

from forecasts.engine import generate_forecast
from matches.models import Match


class Command(BaseCommand):
    help = (
        "Genera pronósticos para partidos finalizados que no tienen "
        "Forecast. Útil para backfill de pronósticos retrospectivos y "
        "evaluar la precisión del modelo sobre partidos ya jugados. "
        "No sobrescribe pronósticos existentes. Procesa en orden "
        "cronológico ascendente para que el motor construya cada "
        "pronóstico con la misma progresión temporal real."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--competition",
            help="Code de competición (ej. PL). Opcional.",
        )
        parser.add_argument(
            "--season",
            help="Temporada (ej. 2024). Opcional.",
        )
        parser.add_argument(
            "--from",
            dest="date_from",
            help="Fecha inicial YYYY-MM-DD (inclusive). Opcional.",
        )
        parser.add_argument(
            "--to",
            dest="date_to",
            help="Fecha final YYYY-MM-DD (inclusive). Opcional.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Número máximo de partidos a procesar.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Solo reporta cuántos partidos habría procesado.",
        )

    def handle(self, *args, **options):
        competition_code = options.get("competition") or ""
        season = options.get("season") or ""
        date_from = options.get("date_from") or ""
        date_to = options.get("date_to") or ""
        limit = options.get("limit")
        dry_run = options.get("dry_run", False)

        qs = (
            Match.objects
            .filter(
                status__in=[Match.Status.FINISHED, Match.Status.AWARDED],
                home_goals__isnull=False,
                away_goals__isnull=False,
                elo_processed=True,
                forecast__isnull=True,
            )
            .select_related("home_team", "away_team", "competition")
            .order_by("utc_date")
        )
        if competition_code:
            qs = qs.filter(competition__code=competition_code)
        if season:
            qs = qs.filter(season=season)
        if date_from:
            qs = qs.filter(utc_date__date__gte=_parse_date(date_from))
        if date_to:
            qs = qs.filter(utc_date__date__lte=_parse_date(date_to))

        total = qs.count()
        self.stdout.write(f"Partidos finalizados sin pronóstico: {total}")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Modo dry-run: no se generó nada."
            ))
            return

        if limit:
            qs = qs[:limit]

        generated = 0
        fallback = 0
        errors = 0
        for match in qs.iterator():
            try:
                forecast = generate_forecast(match)
                if forecast is not None:
                    generated += 1
                    if forecast.is_fallback:
                        fallback += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(
                    f"  Error en partido {match.id_api}: {exc}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"Pronósticos generados: {generated} "
            f"({fallback} fallback solo Elo) | Errores: {errors}"
        ))


def _parse_date(value):
    """Parsea YYYY-MM-DD devolviendo date o lanza ValueError si inválido."""
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from forecasts.models import Forecast
from matches.models import Match


class Command(BaseCommand):
    help = (
        "Elimina pronósticos y partidos programados más allá de la ventana "
        "semanal. Los datos lejanos (fechas, forma reciente, Elo) cambian "
        "con el tiempo, por lo que no tiene sentido mantenerlos."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.FORECAST_SCHEDULE_DAYS,
            help="Ventana de días hacia adelante (default: pronóstico semanal).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostrar lo que se eliminaría sin realizar cambios.",
        )

    def handle(self, *args, **options):
        days = options.get("days", settings.FORECAST_SCHEDULE_DAYS)
        dry_run = options.get("dry_run", False)
        horizon = timezone.now() + timedelta(days=days)

        forecasts_qs = Forecast.objects.filter(match__utc_date__gt=horizon)
        matches_qs = Match.objects.filter(
            utc_date__gt=horizon,
            status__in=[Match.Status.SCHEDULED, Match.Status.TIMED],
        )

        forecasts_count = forecasts_qs.count()
        matches_count = matches_qs.count()

        self.stdout.write(
            f"Horizonte: {horizon.date().isoformat()} (hoy + {days} días)"
        )
        self.stdout.write(
            f"Pronósticos fuera de ventana: {forecasts_count}"
        )
        self.stdout.write(
            f"Partidos programados fuera de ventana: {matches_count}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Modo dry-run: no se eliminó nada."
            ))
            return

        deleted_forecasts, _ = forecasts_qs.delete()
        deleted_matches, _ = matches_qs.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Eliminados: {deleted_forecasts} pronósticos, "
            f"{deleted_matches} partidos programados."
        ))

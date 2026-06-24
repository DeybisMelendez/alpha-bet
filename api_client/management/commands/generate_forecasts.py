from django.conf import settings
from django.core.management.base import BaseCommand

from forecasts.engine import generate_for_scheduled_matches


class Command(BaseCommand):
    help = (
        "Genera pronósticos para partidos programados dentro de la ventana "
        "semanal."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            help="Número máximo de partidos a procesar.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=settings.FORECAST_SCHEDULE_DAYS,
            help="Ventana de días hacia adelante (default: pronóstico semanal).",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        days = options.get("days", settings.FORECAST_SCHEDULE_DAYS)
        generated, fallback = generate_for_scheduled_matches(
            limit=limit, days=days
        )
        self.stdout.write(self.style.SUCCESS(
            f"Pronósticos: {generated} generados "
            f"({fallback} fallback solo Elo)"
        ))

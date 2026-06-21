from django.core.management.base import BaseCommand

from forecasts.engine import generate_for_scheduled_matches


class Command(BaseCommand):
    help = "Genera pronósticos para partidos programados sin pronóstico"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            help="Número máximo de partidos a procesar.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        generated, skipped = generate_for_scheduled_matches(limit=limit)
        self.stdout.write(self.style.SUCCESS(
            f"Pronósticos: {generated} generados, {skipped} omitidos"
        ))

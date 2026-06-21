from django.core.management.base import BaseCommand

from elo.engine import process_pending_matches


class Command(BaseCommand):
    help = "Procesa partidos finalizados sin Elo aplicado"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            help="Número máximo de partidos a procesar.",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        processed = process_pending_matches(limit=limit)
        self.stdout.write(self.style.SUCCESS(
            f"Elo aplicado a {processed} partidos"
        ))

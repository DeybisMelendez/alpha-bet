from django.core.management.base import BaseCommand

from api_client.client import FootballDataClient
from api_client.sync import discover_competitions


class Command(BaseCommand):
    help = (
        "Descubre y registra las competiciones del plan Free de "
        "football-data.org (/v4/competitions). Filtra por "
        "FOOTBALL_DATA_FREE_COMPETITION_CODES (12 ligas/copas). Idempotente: "
        "actualiza existentes."
    )

    def handle(self, *args, **options):
        client = FootballDataClient()
        self.stdout.write(
            "Descargando competiciones desde /v4/competitions..."
        )
        try:
            response = client.get_competitions()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(
                f"Error obteniendo /v4/competitions: {exc}"
            ))
            return

        self.stdout.write(f"  {len(response)} competiciones recibidas.")
        created, updated, skipped = discover_competitions(response)

        self.stdout.write(self.style.SUCCESS(
            f"Descubrimiento: {created} nuevas, {updated} actualizadas, "
            f"{skipped} omitidas (fuera del plan Free)."
        ))

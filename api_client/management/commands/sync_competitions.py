from django.core.management.base import BaseCommand

from api_client.client import ApiFootballClient
from api_client.sync import discover_leagues


class Command(BaseCommand):
    help = (
        "Descubre y registra competiciones desde API-Football (/leagues). "
        "Filtra client-side descartando femenil/juvenil/futsal/beach/esports. "
        "Idempotente: actualiza existentes. Sin args usa /leagues?current=true "
        "(solo ligas en temporada activa, 1 petición). Con --all descarga el "
        "catálogo completo (más grande)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Descargar el catálogo completo (/leagues sin current=true).",
        )

    def handle(self, *args, **options):
        client = ApiFootballClient()
        current = not options["all"]
        label = "actuales" if current else "totales"
        self.stdout.write(
            f"Descargando competiciones {label} desde /leagues..."
        )
        try:
            response = client.get_leagues(current=current)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Error obteniendo /leagues: {exc}"))
            return

        self.stdout.write(f"  {len(response)} competiciones recibidas.")
        created, updated, skipped = discover_leagues(response)

        self.stdout.write(self.style.SUCCESS(
            f"Descubrimiento: {created} nuevas, {updated} actualizadas, "
            f"{skipped} omitidas (filtro)."
        ))
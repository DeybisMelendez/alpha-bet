from django.core.management.base import BaseCommand

from elo.engine import regress_elo
from teams.models import TeamCompetition


class Command(BaseCommand):
    help = (
        "Regresión de Elo entre temporadas (docs/elo.md §Regresión): "
        "EloNuevo = 0.9·EloAnterior + 0.1·EloPromedioLiga. Idempotente: "
        "omite equipos ya regresados a la temporada indicada."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "season",
            help="Temporada hacia la cual regresar (ej. 2024).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostrar cuántos equipos se actualizarían sin modificar.",
        )
        parser.add_argument(
            "--regress-factor",
            type=float,
            default=0.90,
            help="Peso del Elo anterior (default 0.90).",
        )
        parser.add_argument(
            "--league-weight",
            type=float,
            default=0.10,
            help="Peso del Elo promedio de la liga (default 0.10).",
        )

    def handle(self, *args, **options):
        season = options["season"]
        dry_run = options["dry_run"]

        teams_in_season = TeamCompetition.objects.filter(
            season=season
        ).values_list("team_id", flat=True).distinct().count()
        self.stdout.write(
            f"Equipos con actividad en la temporada {season}: "
            f"{teams_in_season}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Modo dry-run: no se realizaron cambios."
            ))
            return

        updated = regress_elo(
            season,
            regress_factor=options["regress_factor"],
            league_weight=options["league_weight"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Regresión aplicada: {updated} equipos actualizados."
        ))
from django.core.management.base import BaseCommand, CommandError

from api_client.client import FootballDataClient
from api_client.sync import ensure_team
from teams.models import Competition, TeamCompetition


class Command(BaseCommand):
    help = (
        "Sincroniza equipos de una competición/temporada desde "
        "football-data.org (/v4/competitions/{id}/teams?season=YYYY)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--competition",
            required=True,
            help="ID de football-data.org de la competición (ej. 2021 PL).",
        )
        parser.add_argument(
            "--season",
            required=True,
            help="Temporada (ej. 2024).",
        )

    def handle(self, *args, **options):
        competition_id = int(options["competition"])
        season = options["season"]

        try:
            competition = Competition.objects.get(id_api=competition_id)
        except Competition.DoesNotExist:
            raise CommandError(
                f"Competición {competition_id} no existe. "
                f"Ejecuta sync_competitions primero."
            )

        client = FootballDataClient()
        try:
            teams_data = client.get_competition_teams(
                competition_id, season=season
            )
        except Exception as exc:
            raise CommandError(f"Error obteniendo equipos: {exc}")

        if not teams_data:
            self.stdout.write(self.style.WARNING(
                f"No hay equipos para competición {competition_id} "
                f"temporada {season}."
            ))
            return

        created = 0
        updated = 0
        links = 0

        for data in teams_data:
            team, created_flag = ensure_team(
                data, competition, season_str=season
            )
            if team is None:
                continue
            if created_flag:
                created += 1
                self.stdout.write(
                    f"  + {team.name} (Elo inicial {team.elo:.0f})"
                )
            else:
                updated += 1
                self.stdout.write(f"  ~ {team.name}")

            _, link_created = TeamCompetition.objects.get_or_create(
                team=team,
                competition=competition,
                season=season,
            )
            if link_created:
                links += 1

        self.stdout.write(self.style.SUCCESS(
            f"Equipos: {created} nuevos, {updated} actualizados, "
            f"{links} vínculos temporada {season}"
        ))

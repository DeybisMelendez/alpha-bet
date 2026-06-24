from django.core.management.base import BaseCommand, CommandError

from api_client.apifootball_sync import ensure_team_af
from api_client.client import ApiFootballClient
from teams.models import Competition, TeamCompetition


class Command(BaseCommand):
    help = (
        "Sincroniza equipos de una liga/temporada desde API-Football. "
        "Solo disponible para temporadas 2022-2024 en el plan Free."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--league",
            required=True,
            help="League ID de API-Football (ej. 262 para Liga MX).",
        )
        parser.add_argument(
            "--season",
            required=True,
            help="Temporada (ej. 2024). Plan Free: 2022-2024.",
        )

    def handle(self, *args, **options):
        league_id = options["league"]
        season = options["season"]

        try:
            competition = Competition.objects.get(
                code=str(league_id),
                source=Competition.Source.APIFOOTBALL,
            )
        except Competition.DoesNotExist:
            raise CommandError(
                f"Competición {league_id} no existe. "
                f"Ejecuta sync_af_competitions primero."
            )

        client = ApiFootballClient()
        try:
            teams_data = client.get_teams(league=league_id, season=season)
        except Exception as exc:
            raise CommandError(f"Error obteniendo equipos: {exc}")

        if not teams_data:
            self.stdout.write(self.style.WARNING(
                f"No hay equipos para liga {league_id} temporada {season}."
            ))
            return

        created = 0
        updated = 0
        links = 0

        for data in teams_data:
            team, created_flag = ensure_team_af(
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

from django.core.management.base import BaseCommand, CommandError

from api_client.client import FootballDataClient
from elo.engine import assign_initial_elo
from teams.models import Competition, Team, TeamCompetition


class Command(BaseCommand):
    help = "Sincroniza equipos de una competición desde football-data.org"

    def add_arguments(self, parser):
        parser.add_argument(
            "--competition",
            required=True,
            help="Código de competición (PL, PD, BL1, SA, FL1, CL, WC)",
        )

    def handle(self, *args, **options):
        code = options["competition"]
        try:
            competition = Competition.objects.get(code=code)
        except Competition.DoesNotExist:
            raise CommandError(
                f"Competición {code} no existe. Ejecuta sync_competitions primero."
            )

        client = FootballDataClient()
        try:
            teams_data = client.get_competition_teams(code)
        except Exception as exc:
            raise CommandError(f"Error obteniendo equipos: {exc}")

        season = competition.current_season
        created = 0
        updated = 0
        links = 0

        for data in teams_data:
            team, created_flag = Team.objects.update_or_create(
                id_api=data["id"],
                source=Team.Source.FOOTBALLDATA,
                defaults={
                    "name": data.get("name", ""),
                    "short_name": data.get("shortName", ""),
                    "tla": data.get("tla", ""),
                    "crest_url": data.get("crest", ""),
                    "founded": data.get("founded"),
                    "venue": data.get("venue", ""),
                    "website": data.get("website", ""),
                },
            )

            if created_flag:
                created += 1
                assign_initial_elo(team, competition, season=season)
                team.save(update_fields=["elo"])
                self.stdout.write(f"  + {team.name} (Elo inicial {team.elo:.0f})")
            else:
                updated += 1
                self.stdout.write(f"  ~ {team.name}")

            if season:
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

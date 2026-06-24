from django.conf import settings
from django.core.management.base import BaseCommand

from elo.engine import assign_initial_elo
from elo.models import EloLog, LeagueStrength
from forecasts.models import Forecast
from matches.models import Match
from teams.models import Team, TeamCompetition


class Command(BaseCommand):
    help = (
        "Reinicia el sistema Elo y los pronósticos para reconstruirlos desde "
        "cero. Elimina pronósticos, logs de Elo y fuerza de ligas; marca "
        "todos los partidos como no procesados y resetea el Elo de los "
        "equipos a su valor inicial."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostrar lo que se resetearía sin realizar cambios.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        forecasts = Forecast.objects.count()
        elo_logs = (
            Match.objects.filter(elo_processed=True).count()
        )
        league_strengths = LeagueStrength.objects.count()
        teams = Team.objects.count()

        self.stdout.write(
            f"Se resetearán:\n"
            f"  Pronósticos: {forecasts}\n"
            f"  Partidos con Elo procesado: {elo_logs}\n"
            f"  LeagueStrength: {league_strengths}\n"
            f"  Equipos: {teams} (Elo y matches_played a valor inicial)"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Modo dry-run: no se realizó ningún cambio."
            ))
            return

        # 1. Eliminar pronósticos, logs de Elo y fuerza de ligas.
        Forecast.objects.all().delete()
        EloLog.objects.all().delete()
        LeagueStrength.objects.all().delete()

        # 2. Marcar todos los partidos como no procesados.
        Match.objects.all().update(
            elo_processed=False,
            home_elo_before=None,
            away_elo_before=None,
            home_elo_after=None,
            away_elo_after=None,
        )

        # 3. Resetear Elo y matches_played de cada equipo.
        # Se usa la TeamCompetition más antigua para asignar el Elo inicial
        # según la liga/temporada en la que el equipo apareció por primera vez.
        reset_teams = 0
        for team in Team.objects.all().iterator():
            link = (
                TeamCompetition.objects.filter(team=team)
                .order_by("season", "pk")
                .first()
            )
            if link is not None:
                assign_initial_elo(team, link.competition, link.season)
            else:
                team.elo = settings.ELO_DEFAULT
            team.matches_played = 0
            team.save(update_fields=["elo", "matches_played"])
            reset_teams += 1

        self.stdout.write(self.style.SUCCESS(
            f"Reset completado: {reset_teams} equipos reseteados, "
            f"{forecasts} pronósticos eliminados, "
            f"{elo_logs} partidos marcados como no procesados."
        ))

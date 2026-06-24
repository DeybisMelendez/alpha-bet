from django.core.management.base import BaseCommand
from django.conf import settings

from api_client.client import FootballDataClient
from elo.models import LeagueStrength
from teams.models import Competition


class Command(BaseCommand):
    help = "Sincroniza competiciones populares desde football-data.org"

    def handle(self, *args, **options):
        client = FootballDataClient()
        codes = settings.FOOTBALL_COMPETITIONS
        created = 0
        updated = 0

        for code in codes:
            try:
                data = client.get_competition(code)
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f"Error obteniendo {code}: {exc}")
                )
                continue

            area = data.get("area", {}) or {}
            season = data.get("currentSeason", {}) or {}
            season_str = season.get("startDate", "")[:4] or ""

            obj, created_flag = Competition.objects.update_or_create(
                id_api=data["id"],
                source=Competition.Source.FOOTBALLDATA,
                defaults={
                    "code": data.get("code", code),
                    "name": data.get("name", ""),
                    "area_name": area.get("name", ""),
                    "area_code": area.get("code", ""),
                    "plan": data.get("plan", ""),
                    "current_season": season_str,
                },
            )

            if season_str:
                LeagueStrength.objects.get_or_create(
                    competition=obj,
                    season=season_str,
                    defaults={"average_elo": settings.ELO_DEFAULT},
                )

            if created_flag:
                created += 1
                self.stdout.write(f"  + {obj.name} ({code})")
            else:
                updated += 1
                self.stdout.write(f"  ~ {obj.name} ({code})")

        self.stdout.write(self.style.SUCCESS(
            f"Competiciones: {created} creadas, {updated} actualizadas"
        ))

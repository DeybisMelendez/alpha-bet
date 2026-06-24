from django.core.management.base import BaseCommand
from django.conf import settings

from api_client.apifootball_sync import ensure_competition_af
from elo.models import LeagueStrength
from teams.models import Competition


class Command(BaseCommand):
    help = (
        "Registra/actualiza las competiciones trackeadas de API-Football "
        "definidas en settings.API_FOOTBALL_LEAGUES. Crea Competition y "
        "LeagueStrength para cada una. No consume peticiones de la API: "
        "usa los metadatos definidos en settings. Usar --enrich para "
        "completar area_name y type desde la API (1 req por liga)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--season",
            help=(
                "Temporada a registrar (ej. 2024). Si se omite, usa la "
                "ultima temporada disponible en API_FOOTBALL_HISTORY_SEASONS."
            ),
        )
        parser.add_argument(
            "--enrich",
            action="store_true",
            help=(
                "Consultar /leagues en API-Football para completar area_name "
                "y type. Consume 1 peticion por liga (29 req). Sin este flag "
                "no hace ninguna peticion."
            ),
        )

    def handle(self, *args, **options):
        season = options.get("season")
        if season is None:
            seasons = settings.API_FOOTBALL_HISTORY_SEASONS
            season = str(seasons[-1]) if seasons else ""

        enrich = options.get("enrich", False)
        client = None
        if enrich:
            from api_client.client import ApiFootballClient
            client = ApiFootballClient()

        created = 0
        updated = 0
        errors = 0

        for league_id, code, name, initial_elo in settings.API_FOOTBALL_LEAGUES:
            try:
                if enrich and client is not None:
                    response = client.get_league(league_id)
                    if response:
                        league_data = response[0]
                        league_data["league"]["id"] = league_id
                        _, was_created = ensure_competition_af(
                            league_data, season
                        )
                    else:
                        raise ValueError("sin respuesta")
                else:
                    # Crear desde settings sin llamar a la API.
                    competition, was_created = (
                        Competition.objects.update_or_create(
                            id_api=league_id,
                            source=Competition.Source.APIFOOTBALL,
                            defaults={
                                "code": code,
                                "name": name,
                                "current_season": season,
                            },
                        )
                    )
                    if season:
                        LeagueStrength.objects.get_or_create(
                            competition=competition,
                            season=season,
                            defaults={"average_elo": initial_elo},
                        )

                if was_created:
                    created += 1
                    self.stdout.write(f"  + {name} ({code})")
                else:
                    updated += 1
                    self.stdout.write(f"  ~ {name} ({code})")
            except Exception as exc:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"  {name} ({code}): {exc}")
                )

        self.stdout.write(self.style.SUCCESS(
            f"Competiciones API-Football: {created} creadas, "
            f"{updated} actualizadas, {errors} errores"
        ))

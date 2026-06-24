from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api_client.client import FootballDataClient
from api_client.sync import ensure_competition, ensure_team, save_match
from elo.engine import apply_elo_update
from forecasts.engine import generate_forecast
from matches.models import Match
from teams.models import Competition


class Command(BaseCommand):
    help = (
        "Sincroniza partidos desde football-data.org dentro de una ventana "
        "semanal. Procesa Elo para finalizados y genera pronósticos para "
        "programados."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--competition",
            help="Código de competición (PL, PD, ...). Si se omite, usa /matches por fecha.",
        )
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=settings.FORECAST_SCHEDULE_DAYS,
            help="Ventana de días hacia adelante (default: pronóstico semanal).",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=settings.SYNC_BACK_DAYS,
            help="Ventana de días hacia atrás para capturar resultados recientes.",
        )
        parser.add_argument(
            "--matchday",
            type=int,
            help="Jornada específica (solo con --competition).",
        )
        parser.add_argument(
            "--no-elo",
            action="store_true",
            help="No procesar Elo tras sincronizar.",
        )
        parser.add_argument(
            "--no-forecasts",
            action="store_true",
            help="No generar pronósticos tras sincronizar.",
        )

    def handle(self, *args, **options):
        client = FootballDataClient()
        code = options.get("competition")
        days_ahead = options.get("days_ahead", settings.FORECAST_SCHEDULE_DAYS)
        days_back = options.get("days_back", settings.SYNC_BACK_DAYS)
        matchday = options.get("matchday")

        today = date.today()
        date_from = (today - timedelta(days=days_back)).isoformat()
        date_to = (today + timedelta(days=days_ahead)).isoformat()

        if code:
            try:
                competition = Competition.objects.get(code=code)
            except Competition.DoesNotExist:
                raise CommandError(
                    f"Competición {code} no existe. Ejecuta sync_competitions primero."
                )
            season = competition.current_season
            self.stdout.write(f"Sincronizando partidos de {competition.name}...")

            try:
                if matchday:
                    # Jornada específica: no filtra por fecha.
                    matches_data = client.get_competition_matches(
                        code, matchday=matchday, season=season
                    )
                else:
                    matches_data = client.get_competition_matches(
                        code, season=season,
                        date_from=date_from, date_to=date_to,
                    )
            except Exception as exc:
                raise CommandError(f"Error obteniendo partidos: {exc}")
        else:
            self.stdout.write(
                f"Sincronizando partidos entre {date_from} y {date_to}..."
            )
            try:
                matches_data = client.get_matches(
                    date_from=date_from, date_to=date_to,
                    competitions=settings.FOOTBALL_COMPETITIONS_ALL,
                )
            except Exception as exc:
                raise CommandError(f"Error obteniendo partidos: {exc}")

        created = 0
        updated = 0
        elo_processed = 0
        forecasts_generated = 0
        forecasts_fallback = 0

        for data in matches_data:
            try:
                comp_data = data.get("competition", {}) or {}
                competition, _ = ensure_competition(comp_data)
                if competition is None:
                    continue

                home_data = data.get("homeTeam", {}) or {}
                away_data = data.get("awayTeam", {}) or {}
                season_data = data.get("season", {}) or {}
                season_str = (season_data.get("startDate", "") or "")[:4] or ""

                home, _ = ensure_team(home_data, competition, season_str)
                away, _ = ensure_team(away_data, competition, season_str)
                if home is None or away is None:
                    continue

                match, created_flag = save_match(
                    data, competition, home, away
                )
                if match is None:
                    continue

                if created_flag:
                    created += 1
                else:
                    updated += 1

                if (
                    not options["no_elo"]
                    and match.is_finished
                    and match.has_result
                    and not match.elo_processed
                ):
                    try:
                        result = apply_elo_update(match)
                        if result is not None:
                            elo_processed += 1
                    except Exception as exc:
                        self.stderr.write(
                            self.style.ERROR(
                                f"Error Elo en partido {match.id_api}: {exc}"
                            )
                        )

                if (
                    not options["no_forecasts"]
                    and match.is_scheduled
                ):
                    try:
                        forecast = generate_forecast(match)
                        if forecast is not None:
                            forecasts_generated += 1
                            if forecast.is_fallback:
                                forecasts_fallback += 1
                    except Exception as exc:
                        self.stderr.write(
                            self.style.ERROR(
                                f"Error pronóstico en partido {match.id_api}: {exc}"
                            )
                        )

            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"Error procesando partido {data.get('id')}: {exc}"
                    )
                )

        self.stdout.write(self.style.SUCCESS(
            f"Partidos: {created} nuevos, {updated} actualizados | "
            f"Elo procesado: {elo_processed} | "
            f"Pronósticos: {forecasts_generated} generados "
            f"({forecasts_fallback} fallback solo Elo)"
        ))

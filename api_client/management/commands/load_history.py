import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api_client.client import FootballDataClient
from api_client.sync import ensure_competition, ensure_team, save_match
from elo.engine import process_pending_matches, recompute_league_strength
from forecasts.engine import generate_for_scheduled_matches
from matches.models import Match


def parse_seasons(seasons_arg, from_season, current_year):
    """Devuelve la lista de temporadas (strings) a cargar.

    --seasons puede ser una lista ('2022,2024,2026') o un rango
    ('2020:2026'). Si no se pasa --seasons, se usa range(from_season,
    current_year + 1).
    """
    if seasons_arg:
        if ":" in seasons_arg:
            start, end = seasons_arg.split(":", 1)
            return [str(y) for y in range(int(start), int(end) + 1)]
        return [s.strip() for s in seasons_arg.split(",") if s.strip()]
    return [str(y) for y in range(from_season, current_year + 1)]


class Command(BaseCommand):
    help = (
        "Carga todo el historial de partidos disponible en la API para las "
        "competiciones indicadas. Procesa Elo en orden cronológico, "
        "recalibra la fuerza de ligas y genera pronósticos en ventana."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seasons",
            help=(
                "Temporadas explícitas: lista '2022,2024,2026' o rango "
                "'2020:2026'. Si se omite, usa --from-season hasta el año "
                "actual."
            ),
        )
        parser.add_argument(
            "--from-season",
            type=int,
            default=2015,
            help=(
                "Año inicial cuando no se pasa --seasons (default 2015). "
                "Carga desde esta temporada hasta el año actual."
            ),
        )
        parser.add_argument(
            "--competitions",
            help="Lista de códigos separados por coma (default: todas).",
        )
        parser.add_argument(
            "--rate-limit-seconds",
            type=float,
            default=7.0,
            help="Segundos entre peticiones para respetar el rate limit "
                 "(default 7, free tier = 10 req/min).",
        )
        parser.add_argument(
            "--no-early-stop",
            action="store_true",
            help=(
                "Desactiva la detención temprana: prueba todas las "
                "temporadas aunque devuelvan vacío."
            ),
        )
        parser.add_argument(
            "--no-elo",
            action="store_true",
            help="No procesar Elo tras cargar los partidos.",
        )
        parser.add_argument(
            "--no-forecasts",
            action="store_true",
            help="No generar pronósticos tras cargar los partidos.",
        )
        parser.add_argument(
            "--no-recompute",
            action="store_true",
            help="No recalibrar LeagueStrength tras procesar Elo.",
        )

    def handle(self, *args, **options):
        client = FootballDataClient()
        rate_limit = options["rate_limit_seconds"]
        early_stop = not options["no_early_stop"]

        if options.get("competitions"):
            codes = [c.strip() for c in options["competitions"].split(",")]
        else:
            codes = settings.FOOTBALL_COMPETITIONS_ALL

        current_year = timezone.now().year
        seasons = parse_seasons(
            options.get("seasons"), options["from_season"], current_year
        )

        self.stdout.write(
            f"Cargando historial...\n"
            f"  Competiciones: {', '.join(codes)}\n"
            f"  Temporadas: {', '.join(seasons)}\n"
            f"  Pausa entre peticiones: {rate_limit}s\n"
            f"  Detención temprana: {'sí' if early_stop else 'no'}"
        )

        stats = {
            "competitions": 0,
            "matches_new": 0,
            "matches_updated": 0,
            "teams_new": 0,
            "teams_existing": 0,
            "api_errors": 0,
            "save_errors": 0,
        }

        request_count = 0
        # Horizonte para omitir almacenar partidos programados lejanos.
        # Los datos de esos partidos (fechas, forma reciente, Elo) cambian
        # con el tiempo, por lo que se sincronizarán posteriormente en la
        # ventana semanal.
        forecast_horizon = timezone.now() + timedelta(
            days=settings.FORECAST_SCHEDULE_DAYS
        )

        last_request_index = len(codes) * len(seasons) - 1
        current_index = 0

        for code in codes:
            empty_streak = 0
            for season in seasons:
                self.stdout.write(
                    f"\n  [{code}] temporada {season}..."
                )

                matches_data, is_available = self._fetch_matches(
                    client, code, season, stats
                )
                request_count += 1

                if matches_data is None:
                    # Error transitorio (ya registrado). No rompe el streak.
                    current_index += 1
                    if current_index < last_request_index:
                        time.sleep(rate_limit)
                    continue

                if not is_available:
                    # 403/404: temporada no disponible en el plan.
                    empty_streak += 1
                    if early_stop and empty_streak >= 2:
                        self.stdout.write(
                            f"    2 temporadas no disponibles consecutivas. "
                            f"Omitiendo temporadas anteriores de {code}."
                        )
                        break
                    current_index += 1
                    if current_index < last_request_index:
                        time.sleep(rate_limit)
                    continue

                if not matches_data:
                    self.stdout.write("    Sin partidos.")
                    empty_streak += 1
                    if early_stop and empty_streak >= 2:
                        self.stdout.write(
                            f"    2 temporadas vacías consecutivas. "
                            f"Omitiendo temporadas anteriores de {code}."
                        )
                        break
                    current_index += 1
                    if current_index < last_request_index:
                        time.sleep(rate_limit)
                    continue

                empty_streak = 0
                self.stdout.write(
                    f"    {len(matches_data)} partidos obtenidos."
                )

                for data in matches_data:
                    try:
                        self._save_match(data, stats, forecast_horizon)
                    except Exception as exc:
                        stats["save_errors"] += 1
                        self.stderr.write(self.style.ERROR(
                            f"    Error guardando partido "
                            f"{data.get('id')}: {exc}"
                        ))

                stats["competitions"] += 1
                current_index += 1
                if current_index < last_request_index:
                    time.sleep(rate_limit)

        self._print_load_summary(stats)

        if not options["no_elo"]:
            self.stdout.write(
                "\nProcesando Elo en orden cronológico..."
            )
            processed = process_pending_matches()
            self.stdout.write(self.style.SUCCESS(
                f"  Elo aplicado a {processed} partidos."
            ))

            if not options["no_recompute"]:
                self.stdout.write(
                    "Recalibrando fuerza de ligas..."
                )
                updated = recompute_league_strength()
                self.stdout.write(self.style.SUCCESS(
                    f"  {updated} registros de LeagueStrength actualizados."
                ))

        if not options["no_forecasts"]:
            self.stdout.write(
                "\nGenerando pronósticos para partidos programados..."
            )
            generated, fallback = generate_for_scheduled_matches()
            self.stdout.write(self.style.SUCCESS(
                f"  Pronósticos: {generated} generados "
                f"({fallback} fallback solo Elo)."
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\nTotal peticiones API: {request_count}"
        ))

    def _fetch_matches(self, client, code, season, stats):
        """Obtiene partidos de una competición/temporada con reintento 429.

        Devuelve (matches_list, is_available). is_available=False cuando la
        temporada no está disponible (403/404), lo que permite que la
        detención temprana funcione. En caso de error transitorio devuelve
        (None, True) para no romper el streak.
        """
        try:
            return client.get_competition_matches(code, season=season), True
        except Exception as exc:
            is_not_available = (
                "403" in str(exc) or "404" in str(exc)
            )
            stats["api_errors"] += 1
            self.stderr.write(self.style.ERROR(
                f"    Error API: {exc}"
            ))
            if "429" in str(exc):
                self.stdout.write(
                    "    Rate limit alcanzado, esperando 60s..."
                )
                time.sleep(60)
                try:
                    return (
                        client.get_competition_matches(
                            code, season=season
                        ),
                        True,
                    )
                except Exception as exc2:
                    stats["api_errors"] += 1
                    self.stderr.write(self.style.ERROR(
                        f"    Error API tras reintento: {exc2}"
                    ))
                    is_not_available = (
                        "403" in str(exc2) or "404" in str(exc2)
                    )
                    return None, not is_not_available
            if is_not_available:
                return [], False
            return None, True

    def _save_match(self, data, stats, forecast_horizon):
        comp_data = data.get("competition", {}) or {}
        if comp_data.get("id") is None:
            return
        competition, comp_created = ensure_competition(comp_data)
        if competition is None:
            return

        home_data = data.get("homeTeam", {}) or {}
        away_data = data.get("awayTeam", {}) or {}
        if home_data.get("id") is None or away_data.get("id") is None:
            return

        season_data = data.get("season", {}) or {}
        season_str = (season_data.get("startDate", "") or "")[:4] or ""

        # Omitir almacenar partidos programados fuera de la ventana semanal.
        # Sus fechas pueden cambiar o posponerse, y se sincronizarán después.
        utc_date_raw = data.get("utcDate")
        if utc_date_raw:
            from django.utils.dateparse import parse_datetime
            utc_date = parse_datetime(utc_date_raw)
            status = data.get("status", Match.Status.SCHEDULED)
            is_scheduled = status in [
                Match.Status.SCHEDULED, Match.Status.TIMED
            ]
            if utc_date is not None and is_scheduled \
                    and utc_date > forecast_horizon:
                return

        home, home_created = ensure_team(
            home_data, competition, season_str
        )
        away, away_created = ensure_team(
            away_data, competition, season_str
        )
        if home is None or away is None:
            return

        if home_created:
            stats["teams_new"] += 1
        else:
            stats["teams_existing"] += 1
        if away_created:
            stats["teams_new"] += 1
        else:
            stats["teams_existing"] += 1

        match, created = save_match(data, competition, home, away)
        if match is None:
            return

        if created:
            stats["matches_new"] += 1
        else:
            stats["matches_updated"] += 1

    def _print_load_summary(self, stats):
        self.stdout.write(self.style.SUCCESS(
            f"\nResumen de carga:\n"
            f"  Competiciones procesadas: {stats['competitions']}\n"
            f"  Partidos: {stats['matches_new']} nuevos, "
            f"{stats['matches_updated']} actualizados\n"
            f"  Equipos: {stats['teams_new']} nuevos, "
            f"{stats['teams_existing']} existentes\n"
            f"  Errores API: {stats['api_errors']}, "
            f"Errores guardado: {stats['save_errors']}"
        ))

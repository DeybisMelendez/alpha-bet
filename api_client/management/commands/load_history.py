import time

from django.conf import settings
from django.core.management.base import BaseCommand

from api_client.client import FootballDataClient
from api_client.sync import ensure_competition, ensure_team, save_match
from elo.engine import process_pending_matches, recompute_league_strength
from forecasts.engine import generate_for_scheduled_matches


class Command(BaseCommand):
    help = (
        "Carga el historial de partidos de todas las competiciones "
        "disponibles en la API gratuita para el año indicado. "
        "Procesa Elo en orden cronológico y recalibra la fuerza de ligas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=2026,
            help="Año objetivo (default 2026). Se cargan las temporadas "
                 "year-1 y year para cubrir partidos de ese año.",
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
        year = options["year"]
        rate_limit = options["rate_limit_seconds"]

        if options.get("competitions"):
            codes = [c.strip() for c in options["competitions"].split(",")]
        else:
            codes = settings.FOOTBALL_COMPETITIONS_ALL

        seasons = [str(year - 1), str(year)]

        self.stdout.write(
            f"Cargando historial para año {year}...\n"
            f"  Competiciones: {', '.join(codes)}\n"
            f"  Temporadas: {', '.join(seasons)}\n"
            f"  Pausa entre peticiones: {rate_limit}s"
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
        for code in codes:
            for season in seasons:
                self.stdout.write(
                    f"\n  [{code}] temporada {season}..."
                )
                try:
                    matches_data = client.get_competition_matches(
                        code, season=season
                    )
                    request_count += 1
                except Exception as exc:
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
                            matches_data = client.get_competition_matches(
                                code, season=season
                            )
                            request_count += 1
                        except Exception as exc2:
                            stats["api_errors"] += 1
                            self.stderr.write(self.style.ERROR(
                                f"    Error API tras reintento: {exc2}"
                            ))
                            continue
                    else:
                        continue

                if not matches_data:
                    self.stdout.write("    Sin partidos.")
                    if code != codes[-1] or season != seasons[-1]:
                        time.sleep(rate_limit)
                    continue

                self.stdout.write(
                    f"    {len(matches_data)} partidos obtenidos."
                )

                for data in matches_data:
                    try:
                        self._save_match(data, stats)
                    except Exception as exc:
                        stats["save_errors"] += 1
                        self.stderr.write(self.style.ERROR(
                            f"    Error guardando partido "
                            f"{data.get('id')}: {exc}"
                        ))

                stats["competitions"] += 1

                if code != codes[-1] or season != seasons[-1]:
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
            generated, skipped = generate_for_scheduled_matches()
            self.stdout.write(self.style.SUCCESS(
                f"  Pronósticos: {generated} generados, "
                f"{skipped} omitidos (historial insuficiente)."
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\nTotal peticiones API: {request_count}"
        ))

    def _save_match(self, data, stats):
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

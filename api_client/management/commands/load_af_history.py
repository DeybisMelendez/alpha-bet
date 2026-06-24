import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api_client.apifootball_sync import (
    ensure_competition_af,
    ensure_team_af,
    save_match_af,
)
from api_client.client import ApiFootballClient
from elo.engine import process_pending_matches, recompute_league_strength
from forecasts.engine import generate_for_scheduled_matches
from matches.models import Match


class Command(BaseCommand):
    help = (
        "Carga el historial de partidos disponibles en API-Football para las "
        "ligas trackeadas (solo temporadas 2022-2024 en plan Free). Procesa "
        "Elo en orden cronológico, recalibra fuerza de ligas y genera "
        "pronósticos en ventana. Respeta rate-limit y presupuesto diario."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--leagues",
            help=(
                "Lista de league IDs separados por coma. Si se omite, usa "
                "todas las de settings.API_FOOTBALL_LEAGUES."
            ),
        )
        parser.add_argument(
            "--seasons",
            help=(
                "Temporadas explícitas: lista '2022,2024' o rango "
                "'2022:2024'. Si se omite, usa API_FOOTBALL_HISTORY_SEASONS."
            ),
        )
        parser.add_argument(
            "--rate-limit-seconds",
            type=float,
            default=settings.API_FOOTBALL_RATE_LIMIT_SECONDS,
            help="Segundos entre peticiones (default 6s).",
        )
        parser.add_argument(
            "--max-requests",
            type=int,
            default=settings.API_FOOTBALL_DAILY_BUDGET,
            help="Presupuesto diario de peticiones (default 80).",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            default=True,
            help=(
                "Omitir ligas/temporadas que ya tienen partidos cargados "
                "(default: activado, ahorra peticiones)."
            ),
        )
        parser.add_argument(
            "--no-skip-existing",
            dest="skip_existing",
            action="store_false",
            help="No omitir ligas/temporadas existentes (forzar recarga).",
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
        client = ApiFootballClient()
        rate_limit = options["rate_limit_seconds"]
        max_requests = options["max_requests"]
        skip_existing = options["skip_existing"]

        # Resolver ligas.
        if options.get("leagues"):
            league_ids = [
                int(x.strip()) for x in options["leagues"].split(",")
            ]
        else:
            league_ids = [
                lid for lid, _, _, _ in settings.API_FOOTBALL_LEAGUES
            ]

        # Resolver temporadas.
        if options.get("seasons"):
            s = options["seasons"]
            if ":" in s:
                start, end = s.split(":", 1)
                seasons = [str(y) for y in range(int(start), int(end) + 1)]
            else:
                seasons = [x.strip() for x in s.split(",") if x.strip()]
        else:
            seasons = [str(y) for y in settings.API_FOOTBALL_HISTORY_SEASONS]

        # Lookup de nombres para logging.
        names = {lid: name for lid, _, name, _ in settings.API_FOOTBALL_LEAGUES}

        self.stdout.write(
            f"Cargando historial API-Football...\n"
            f"  Ligas: {len(league_ids)}\n"
            f"  Temporadas: {', '.join(seasons)}\n"
            f"  Pausa entre peticiones: {rate_limit}s\n"
            f"  Presupuesto: {max_requests} req\n"
            f"  Saltar existentes: {'sí' if skip_existing else 'no'}"
        )

        stats = {
            "matches_new": 0,
            "matches_updated": 0,
            "teams_new": 0,
            "teams_existing": 0,
            "seasons_skipped": 0,
            "api_errors": 0,
            "save_errors": 0,
        }

        request_count = 0
        total_planned = len(league_ids) * len(seasons)

        for league_id in league_ids:
            name = names.get(league_id, str(league_id))

            for season in seasons:
                if request_count >= max_requests:
                    self.stdout.write(self.style.WARNING(
                        f"\nPresupuesto diario alcanzado ({max_requests} req). "
                        f"Reejecuta mañana para continuar."
                    ))
                    self._print_summary(stats, request_count)
                    self._post_load(options, stats)
                    return

                # Idempotencia: omitir si ya hay partidos de esta liga/temporada.
                if skip_existing and self._season_has_matches(league_id, season):
                    stats["seasons_skipped"] += 1
                    request_count += 1
                    self.stdout.write(
                        f"  [{name}] {season}: ya cargada, omitiendo."
                    )
                    if request_count < total_planned:
                        time.sleep(rate_limit)
                    continue

                self.stdout.write(f"  [{name}] {season}...")

                try:
                    fixtures = client.get_fixtures(
                        league=league_id, season=season
                    )
                except Exception as exc:
                    stats["api_errors"] += 1
                    self.stderr.write(self.style.ERROR(
                        f"    Error API: {exc}"
                    ))
                    if "429" in str(exc):
                        self.stdout.write(
                            "    Rate limit, esperando 60s..."
                        )
                        time.sleep(60)
                        try:
                            fixtures = client.get_fixtures(
                                league=league_id, season=season
                            )
                        except Exception as exc2:
                            stats["api_errors"] += 1
                            self.stderr.write(self.style.ERROR(
                                f"    Error API tras reintento: {exc2}"
                            ))
                            request_count += 1
                            if request_count < total_planned:
                                time.sleep(rate_limit)
                            continue
                    else:
                        request_count += 1
                        if request_count < total_planned:
                            time.sleep(rate_limit)
                        continue

                request_count += 1

                if not fixtures:
                    self.stdout.write("    Sin partidos.")
                else:
                    self.stdout.write(
                        f"    {len(fixtures)} partidos obtenidos."
                    )
                    for fx in fixtures:
                        try:
                            self._save_fixture(fx, league_id, season, stats)
                        except Exception as exc:
                            stats["save_errors"] += 1
                            self.stderr.write(self.style.ERROR(
                                f"    Error guardando fixture "
                                f"{fx.get('fixture', {}).get('id')}: {exc}"
                            ))

                if request_count < total_planned:
                    time.sleep(rate_limit)

        self._print_summary(stats, request_count)
        self._post_load(options, stats)

    def _season_has_matches(self, league_id, season):
        from teams.models import Competition
        comp = Competition.objects.filter(
            code=str(league_id),
            source=Competition.Source.APIFOOTBALL,
        ).first()
        if comp is None:
            return False
        return Match.objects.filter(
            competition=comp, season=season
        ).exists()

    def _save_fixture(self, fx, league_id, season, stats):
        league = fx.get("league", {}) or {}
        league_data = {"league": league, "country": {}}
        competition, _ = ensure_competition_af(league_data, season)
        if competition is None:
            return

        teams = fx.get("teams", {}) or {}
        home_data = teams.get("home", {}) or {}
        away_data = teams.get("away", {}) or {}

        home, home_created = ensure_team_af(
            home_data, competition, season_str=season
        )
        away, away_created = ensure_team_af(
            away_data, competition, season_str=season
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

        match, created = save_match_af(
            fx, competition, home, away, season_str=season
        )
        if match is None:
            return
        if created:
            stats["matches_new"] += 1
        else:
            stats["matches_updated"] += 1

    def _print_summary(self, stats, request_count):
        self.stdout.write(self.style.SUCCESS(
            f"\nResumen de carga API-Football:\n"
            f"  Peticiones API: {request_count}\n"
            f"  Partidos: {stats['matches_new']} nuevos, "
            f"{stats['matches_updated']} actualizados\n"
            f"  Equipos: {stats['teams_new']} nuevos, "
            f"{stats['teams_existing']} existentes\n"
            f"  Temporadas omitidas (ya cargadas): {stats['seasons_skipped']}\n"
            f"  Errores API: {stats['api_errors']}, "
            f"Errores guardado: {stats['save_errors']}"
        ))

    def _post_load(self, options, stats):
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

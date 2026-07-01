import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api_client.client import FootballDataClient
from api_client.models import BackfillJob
from api_client.sync import (
    ensure_competition,
    ensure_team,
    save_match,
)
from elo.engine import (
    apply_elo_update,
    process_pending_matches,
    recompute_league_strength,
)
from forecasts.engine import generate_for_scheduled_matches
from teams.models import Competition
from matches.models import Match

logger = logging.getLogger("alpha")


class Command(BaseCommand):
    help = (
        "Backfill progresivo del historial de partidos (competición × "
        "temporada) vía football-data.org, respetando el presupuesto diario "
        "de la API. Usa una cola persistente (BackfillJob) para reanudar tras "
        "interrupciones. Idempotente: save_match es update_or_create por "
        "id_api. El plan Free permite temporadas históricas de las 12 "
        "competiciones accesibles."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            action="store_true",
            help=(
                "Crea los BackfillJob PENDING para todas las competiciones "
                "registradas × temporadas del rango (--from/--to). No consume "
                "peticiones. Idempotente."
            ),
        )
        parser.add_argument(
            "--from",
            dest="from_year",
            type=int,
            default=2020,
            help="Año inicial del rango de backfill (default: 2020).",
        )
        parser.add_argument(
            "--to",
            dest="to_year",
            type=int,
            default=timezone.now().year,
            help="Año final del rango de backfill (default: año actual).",
        )
        parser.add_argument(
            "--competitions",
            help=(
                "Lista de IDs de football-data.org separados por coma. Si se "
                "omite, usa todas las competiciones registradas en la BD."
            ),
        )
        parser.add_argument(
            "--seasons",
            help=(
                "Temporadas explícitas: lista '2020,2024' o rango "
                "'2020:2026'. Si se omite, usa --from..--to."
            ),
        )
        parser.add_argument(
            "--max-requests",
            type=int,
            default=settings.FOOTBALL_DATA_DAILY_BUDGET,
            help=(
                "Presupuesto diario de peticiones (default: "
                f"{settings.FOOTBALL_DATA_DAILY_BUDGET})."
            ),
        )
        parser.add_argument(
            "--rate-limit-seconds",
            type=float,
            default=settings.FOOTBALL_DATA_RATE_LIMIT_SECONDS,
            help="Pausa entre peticiones (default plan Free: 6s).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Limpia BackfillJob en PENDING/IN_PROGRESS/ERROR antes de empezar.",
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
        if options["reset"]:
            self._reset_jobs()

        if options["seed"]:
            self._seed_jobs(
                from_year=options["from_year"],
                to_year=options["to_year"],
                competitions_arg=options.get("competitions"),
                seasons_arg=options.get("seasons"),
            )
            return

        self._run_backfill(options)

    # ------------------------------------------------------------------ #

    def _resolve_seasons(self, from_year, to_year, seasons_arg):
        if seasons_arg:
            if ":" in seasons_arg:
                start, end = seasons_arg.split(":", 1)
                return [str(y) for y in range(int(start), int(end) + 1)]
            return [x.strip() for x in seasons_arg.split(",") if x.strip()]
        return [str(y) for y in range(from_year, to_year + 1)]

    def _resolve_competitions(self, competitions_arg):
        if competitions_arg:
            ids = [int(x.strip()) for x in competitions_arg.split(",")]
            qs = Competition.objects.filter(id_api__in=ids)
            missing = set(ids) - set(qs.values_list("id_api", flat=True))
            if missing:
                self.stdout.write(self.style.WARNING(
                    f"Competiciones no registradas (se omiten): {sorted(missing)}"
                ))
            return list(qs)
        return list(Competition.objects.all().order_by("id_api"))

    def _seed_jobs(self, from_year, to_year, competitions_arg, seasons_arg):
        seasons = self._resolve_seasons(from_year, to_year, seasons_arg)
        competitions = self._resolve_competitions(competitions_arg)
        if not competitions:
            self.stdout.write(self.style.WARNING(
                "No hay competiciones registradas. Ejecuta sync_competitions."
            ))
            return

        created = 0
        existing = 0
        for comp in competitions:
            for season in seasons:
                _, was_created = BackfillJob.objects.get_or_create(
                    competition=comp,
                    season=season,
                    defaults={"status": BackfillJob.Status.PENDING},
                )
                if was_created:
                    created += 1
                else:
                    existing += 1

        total = len(competitions) * len(seasons)
        self.stdout.write(self.style.SUCCESS(
            f"Cola sembrada: {created} nuevos PENDING, {existing} ya "
            f"existían. Total trabajos: {total} "
            f"({len(competitions)} ligas × {len(seasons)} temporadas)."
        ))

    def _reset_jobs(self):
        qs = BackfillJob.objects.filter(
            status__in=[
                BackfillJob.Status.PENDING,
                BackfillJob.Status.IN_PROGRESS,
                BackfillJob.Status.ERROR,
            ]
        )
        count = qs.count()
        qs.delete()
        self.stdout.write(self.style.WARNING(
            f"Limpiados {count} trabajos PENDING/IN_PROGRESS/ERROR."
        ))

    def _run_backfill(self, options):
        client = FootballDataClient()
        max_requests = options["max_requests"]
        rate_limit = options["rate_limit_seconds"]
        no_elo = options["no_elo"]

        competitions_arg = options.get("competitions")
        seasons_arg = options.get("seasons")
        seasons_filter = None
        if seasons_arg:
            seasons_filter = self._resolve_seasons(
                options["from_year"], options["to_year"], seasons_arg
            )
        comp_ids_filter = None
        if competitions_arg:
            comp_ids_filter = [int(x.strip()) for x in competitions_arg.split(",")]

        pending = BackfillJob.objects.filter(
            status=BackfillJob.Status.PENDING
        ).select_related("competition").order_by("competition__id_api", "season")
        if comp_ids_filter:
            pending = pending.filter(competition__id_api__in=comp_ids_filter)
        if seasons_filter:
            pending = pending.filter(season__in=seasons_filter)

        total_pending = pending.count()
        if total_pending == 0:
            self.stdout.write(self.style.WARNING(
                "No hay trabajos PENDING. Ejecuta load_history --seed primero."
            ))
            return

        self.stdout.write(
            f"Backfill: {total_pending} trabajos PENDING | "
            f"presupuesto {max_requests} req | pausa {rate_limit}s"
        )

        stats = {
            "matches_new": 0,
            "matches_updated": 0,
            "teams_new": 0,
            "teams_existing": 0,
            "jobs_done": 0,
            "jobs_empty": 0,
            "api_errors": 0,
            "save_errors": 0,
        }

        request_count = 0
        for job in pending:
            if request_count >= max_requests:
                self.stdout.write(self.style.WARNING(
                    f"\nPresupuesto diario alcanzado ({max_requests} req). "
                    f"Reejecuta mañana para continuar."
                ))
                break

            # Cortar si la API reporta poco remaining (plan Free: 10/min).
            if (
                client.last_rate_remaining is not None
                and client.last_rate_remaining < 2
            ):
                self.stdout.write(self.style.WARNING(
                    f"\nRate-limit remaining bajo "
                    f"({client.last_rate_remaining}). Deteniendo."
                ))
                break

            self._process_job(job, client, rate_limit, stats, no_elo)
            request_count += 1
            time.sleep(rate_limit)

        self._print_summary(stats, request_count)
        self._post_load(options)

    def _process_job(self, job, client, rate_limit, stats, no_elo):
        comp = job.competition
        season = job.season
        name = comp.name or str(comp.id_api)

        job.status = BackfillJob.Status.IN_PROGRESS
        job.last_run_at = timezone.now()
        job.save(update_fields=["status", "last_run_at"])

        self.stdout.write(f"  [{name}] {season}...")

        try:
            matches = client.get_competition_matches(
                comp.id_api, season=season
            )
        except Exception as exc:
            stats["api_errors"] += 1
            job.status = BackfillJob.Status.ERROR
            job.error_msg = str(exc)[:500]
            job.save(update_fields=["status", "error_msg"])
            self.stderr.write(self.style.ERROR(f"    Error API: {exc}"))
            if "429" in str(exc):
                reset = 60
                self.stdout.write(
                    f"    Rate limit, esperando {reset}s..."
                )
                time.sleep(reset)
                try:
                    matches = client.get_competition_matches(
                        comp.id_api, season=season
                    )
                except Exception as exc2:
                    stats["api_errors"] += 1
                    job.error_msg = str(exc2)[:500]
                    job.save(update_fields=["error_msg"])
                    self.stderr.write(self.style.ERROR(
                        f"    Error API tras reintento: {exc2}"
                    ))
                    return
            else:
                return

        if not matches:
            self.stdout.write("    Sin partidos.")
            job.status = BackfillJob.Status.EMPTY
            job.save(update_fields=["status"])
            stats["jobs_empty"] += 1
            return

        self.stdout.write(f"    {len(matches)} partidos obtenidos.")
        for m in matches:
            try:
                self._save_match(m, comp, season, stats)
            except Exception as exc:
                stats["save_errors"] += 1
                self.stderr.write(self.style.ERROR(
                    f"    Error guardando partido {m.get('id')}: {exc}"
                ))

        job.status = BackfillJob.Status.DONE
        job.fixtures_count = len(matches)
        job.save(update_fields=["status", "fixtures_count"])
        stats["jobs_done"] += 1

        # Procesar Elo cronológicamente por competición×temporada.
        if no_elo:
            return
        pending = Match.objects.filter(
            competition=comp, season=season,
            elo_processed=False, status__in=[
                Match.Status.FINISHED, Match.Status.AWARDED
            ],
            home_goals__isnull=False, away_goals__isnull=False,
        ).order_by("utc_date")
        for match in pending:
            try:
                apply_elo_update(match, regenerate_forecasts=False)
            except Exception:
                logger.exception(
                    "Error aplicando Elo al partido %s", match.id_api
                )

    def _save_match(self, m, competition, season, stats):
        comp_block = m.get("competition", {}) or {}
        comp, _ = ensure_competition(comp_block, season)
        if comp is None:
            comp = competition

        home_data = m.get("homeTeam", {}) or {}
        away_data = m.get("awayTeam", {}) or {}

        home, home_created = ensure_team(
            home_data, comp, season_str=season
        )
        away, away_created = ensure_team(
            away_data, comp, season_str=season
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

        match, created = save_match(
            m, comp, home, away, season_str=season
        )
        if match is None:
            return
        if created:
            stats["matches_new"] += 1
        else:
            stats["matches_updated"] += 1

    def _print_summary(self, stats, request_count):
        self.stdout.write(self.style.SUCCESS(
            f"\nResumen de backfill:\n"
            f"  Peticiones API: {request_count}\n"
            f"  Trabajos: {stats['jobs_done']} completados, "
            f"{stats['jobs_empty']} sin partidos\n"
            f"  Partidos: {stats['matches_new']} nuevos, "
            f"{stats['matches_updated']} actualizados\n"
            f"  Equipos: {stats['teams_new']} nuevos, "
            f"{stats['teams_existing']} existentes\n"
            f"  Errores API: {stats['api_errors']}, "
            f"Errores guardado: {stats['save_errors']}"
        ))

    def _post_load(self, options):
        if not options["no_elo"]:
            self.stdout.write(
                "\nProcesando Elo pendiente (partidos sueltos)..."
            )
            processed = process_pending_matches()
            self.stdout.write(self.style.SUCCESS(
                f"  Elo aplicado a {processed} partidos adicionales."
            ))

            if not options["no_recompute"]:
                self.stdout.write("Recalibrando fuerza de ligas...")
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

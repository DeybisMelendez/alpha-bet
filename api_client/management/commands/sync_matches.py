from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand

from api_client.client import ApiFootballClient
from api_client.sync import (
    ensure_competition,
    ensure_team,
    save_match,
    save_match_statistics,
)
from elo.engine import apply_elo_update
from forecasts.engine import generate_forecast
from teams.models import Competition


class Command(BaseCommand):
    help = (
        "Sincroniza partidos desde API-Football consultando date=hoy-1, hoy "
        "y hoy+1 (3 peticiones). Filtra client-side a las competiciones ya "
        "registradas en la BD (trackeadas vía sync_competitions). Procesa Elo "
        "para finalizados y genera pronósticos para programados."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-back",
            type=int,
            default=1,
            help="Días hacia atrás a consultar (default: 1).",
        )
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=1,
            help="Días hacia adelante a consultar (default: 1).",
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
        parser.add_argument(
            "--no-stats",
            action="store_true",
            help="No descargar estadísticas del partido (remates, córners, etc.).",
        )

    def handle(self, *args, **options):
        client = ApiFootballClient()
        no_elo = options["no_elo"]
        no_forecasts = options["no_forecasts"]
        no_stats = options["no_stats"]
        days_back = options["days_back"]
        days_ahead = options["days_ahead"]

        # IDs de competiciones ya registradas para filtrado client-side.
        tracked_ids = set(
            Competition.objects.values_list("id_api", flat=True)
        )
        if not tracked_ids:
            self.stdout.write(self.style.WARNING(
                "No hay competiciones registradas. Ejecuta sync_competitions "
                "primero."
            ))
            return

        today = date.today()
        dates = [
            (today + timedelta(days=offset)).isoformat()
            for offset in range(-days_back, days_ahead + 1)
        ]

        stats = {
            "matches_new": 0,
            "matches_updated": 0,
            "elo_processed": 0,
            "forecasts_generated": 0,
            "forecasts_fallback": 0,
            "stats_saved": 0,
            "skipped": 0,
            "errors": 0,
        }

        for date_str in dates:
            self.stdout.write(f"  Consultando date={date_str}...")
            try:
                fixtures = client.get_fixtures_by_date(date_str)
            except Exception as exc:
                stats["errors"] += 1
                self.stderr.write(
                    self.style.ERROR(f"  Error obteniendo {date_str}: {exc}")
                )
                continue

            for fx in fixtures:
                league = fx.get("league", {}) or {}
                league_id = league.get("id")
                if league_id not in tracked_ids:
                    stats["skipped"] += 1
                    continue

                season_str = str(league.get("season") or "")
                try:
                    self._process_fixture(
                        fx, league, season_str,
                        no_elo, no_forecasts, no_stats, stats, client,
                    )
                except Exception as exc:
                    stats["errors"] += 1
                    self.stderr.write(self.style.ERROR(
                        f"  Error en fixture "
                        f"{fx.get('fixture', {}).get('id')}: {exc}"
                    ))

        self.stdout.write(self.style.SUCCESS(
            f"API-Football: {stats['matches_new']} nuevos, "
            f"{stats['matches_updated']} actualizados | "
            f"Elo: {stats['elo_processed']} | "
            f"Pronósticos: {stats['forecasts_generated']} "
            f"({stats['forecasts_fallback']} fallback) | "
            f"Stats: {stats['stats_saved']} | "
            f"Omitidos (no tracked): {stats['skipped']} | "
            f"Errores: {stats['errors']}"
        ))

    def _process_fixture(self, fx, league, season_str,
                         no_elo, no_forecasts, no_stats, stats, client):
        competition, _ = ensure_competition(
            {"league": league, "country": {}}, season_str
        )
        if competition is None:
            return

        teams = fx.get("teams", {}) or {}
        home_data = teams.get("home", {}) or {}
        away_data = teams.get("away", {}) or {}

        home, _ = ensure_team(home_data, competition, season_str)
        away, _ = ensure_team(away_data, competition, season_str)
        if home is None or away is None:
            return

        match, created = save_match(
            fx, competition, home, away, season_str=season_str
        )
        if match is None:
            return

        if created:
            stats["matches_new"] += 1
        else:
            stats["matches_updated"] += 1

        if (
            not no_elo
            and match.is_finished
            and match.has_result
            and not match.elo_processed
        ):
            try:
                result = apply_elo_update(match)
                if result is not None:
                    stats["elo_processed"] += 1
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"  Error Elo en partido {match.id_api}: {exc}"
                ))

        # Estadísticas del partido (remates, córners, posesión, etc.).
        # docs/api.md: tras finalizar el encuentro se descargan todas
        # las estadísticas disponibles. Si fallara (plan Free en algunas
        # competiciones) se atrapa para no romper el sync de partidos.
        if not no_stats and match.is_finished:
            try:
                saved = save_match_statistics(match, client, fixture_data=fx)
                stats["stats_saved"] += saved
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"  Error stats en partido {match.id_api}: {exc}"
                ))

        if not no_forecasts and match.is_scheduled:
            try:
                forecast = generate_forecast(match)
                if forecast is not None:
                    stats["forecasts_generated"] += 1
                    if forecast.is_fallback:
                        stats["forecasts_fallback"] += 1
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"  Error pronóstico en partido {match.id_api}: {exc}"
                ))
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from api_client.client import FootballDataClient
from api_client.sync import (
    ensure_competition,
    ensure_team,
    save_match,
)
from elo.engine import apply_elo_update
from forecasts.engine import generate_forecast
from teams.models import Competition


class Command(BaseCommand):
    help = (
        "Sincroniza partidos desde football-data.org (/v4/matches con "
        "dateFrom/dateTo). Una sola petición cubre toda la ventana. Filtra "
        "client-side a las competiciones registradas. Procesa Elo para "
        "finalizados y genera pronósticos para programados."
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

    def handle(self, *args, **options):
        client = FootballDataClient()
        no_elo = options["no_elo"]
        no_forecasts = options["no_forecasts"]
        days_back = options["days_back"]
        days_ahead = options["days_ahead"]

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
        date_from = (today - timedelta(days=days_back)).isoformat()
        date_to = (today + timedelta(days=days_ahead)).isoformat()

        stats = {
            "matches_new": 0,
            "matches_updated": 0,
            "elo_processed": 0,
            "forecasts_generated": 0,
            "forecasts_fallback": 0,
            "skipped": 0,
            "errors": 0,
        }

        self.stdout.write(
            f"  Consultando /v4/matches dateFrom={date_from} "
            f"dateTo={date_to}..."
        )
        try:
            matches = client.get_matches(date_from=date_from, date_to=date_to)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(
                f"  Error obteniendo partidos: {exc}"
            ))
            return

        self.stdout.write(f"  {len(matches)} partidos recibidos.")

        for m in matches:
            comp_block = m.get("competition", {}) or {}
            comp_id = comp_block.get("id")
            if comp_id not in tracked_ids:
                stats["skipped"] += 1
                continue

            season_block = m.get("season", {}) or {}
            season_str = str(season_block.get("startDate", "") or "")[:4]

            try:
                self._process_match(
                    m, comp_block, season_str,
                    no_elo, no_forecasts, stats,
                )
            except Exception as exc:
                stats["errors"] += 1
                self.stderr.write(self.style.ERROR(
                    f"  Error en partido {m.get('id')}: {exc}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"football-data.org: {stats['matches_new']} nuevos, "
            f"{stats['matches_updated']} actualizados | "
            f"Elo: {stats['elo_processed']} | "
            f"Pronósticos: {stats['forecasts_generated']} "
            f"({stats['forecasts_fallback']} fallback) | "
            f"Omitidos (no tracked): {stats['skipped']} | "
            f"Errores: {stats['errors']}"
        ))

    def _process_match(self, m, comp_block, season_str,
                       no_elo, no_forecasts, stats):
        competition, _ = ensure_competition(comp_block, season_str)
        if competition is None:
            return

        home_data = m.get("homeTeam", {}) or {}
        away_data = m.get("awayTeam", {}) or {}

        home, _ = ensure_team(home_data, competition, season_str)
        away, _ = ensure_team(away_data, competition, season_str)
        if home is None or away is None:
            return

        match, created = save_match(
            m, competition, home, away, season_str=season_str
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

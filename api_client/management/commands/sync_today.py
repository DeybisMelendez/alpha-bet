from datetime import date

from django.core.management.base import BaseCommand

from api_client.client import FootballDataClient
from api_client.sync import ensure_competition, ensure_team, save_match
from elo.engine import apply_elo_update
from forecasts.engine import generate_forecast
from matches.models import Match


class Command(BaseCommand):
    help = (
        "Busca los partidos del día. Registra equipos y competiciones nuevas "
        "con sus datos, asigna Elo inicial y calcula pronósticos."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Fecha específica (YYYY-MM-DD). Por defecto hoy.",
        )
        parser.add_argument(
            "--enrich",
            action="store_true",
            help=(
                "Consultar /teams/{id} y /competitions/{code} para datos "
                "completos (founded, venue, website, area). Consume más "
                "peticiones de la API."
            ),
        )
        parser.add_argument(
            "--no-elo",
            action="store_true",
            help="No procesar Elo para partidos finalizados.",
        )
        parser.add_argument(
            "--no-forecasts",
            action="store_true",
            help="No generar pronósticos para partidos programados.",
        )

    def handle(self, *args, **options):
        client = FootballDataClient()

        if options.get("date"):
            try:
                target_date = date.fromisoformat(options["date"])
            except ValueError:
                self.stderr.write(self.style.ERROR(
                    "Formato de fecha inválido. Usar YYYY-MM-DD."
                ))
                return
        else:
            target_date = date.today()

        date_str = target_date.isoformat()
        self.stdout.write(f"Buscando partidos del día {date_str}...")

        try:
            matches_data = client.get_matches(
                date_from=date_str, date_to=date_str
            )
        except Exception as exc:
            self.stderr.write(self.style.ERROR(
                f"Error obteniendo partidos: {exc}"
            ))
            return

        if not matches_data:
            self.stdout.write(self.style.WARNING(
                f"No hay partidos para {date_str}."
            ))
            return

        self.stdout.write(f"Se encontraron {len(matches_data)} partidos.")

        enrich = options.get("enrich", False)
        no_elo = options.get("no_elo", False)
        no_forecasts = options.get("no_forecasts", False)

        stats = {
            "matches_new": 0,
            "matches_updated": 0,
            "teams_new": 0,
            "teams_existing": 0,
            "competitions_new": 0,
            "competitions_existing": 0,
            "elo_processed": 0,
            "forecasts_generated": 0,
            "forecasts_fallback": 0,
            "errors": 0,
        }

        for data in matches_data:
            try:
                self._process_match(
                    data, client, enrich, no_elo, no_forecasts, stats
                )
            except Exception as exc:
                stats["errors"] += 1
                self.stderr.write(self.style.ERROR(
                    f"Error procesando partido {data.get('id')}: {exc}"
                ))

        self._print_summary(stats, date_str)

    def _process_match(self, data, client, enrich, no_elo, no_forecasts, stats):
        comp_data = data.get("competition", {}) or {}
        competition, comp_created = ensure_competition(
            comp_data, client=client, enrich=enrich
        )
        if competition is None:
            return
        if comp_created:
            stats["competitions_new"] += 1
            self.stdout.write(
                f"  + Competición: {competition.name} ({competition.code})"
            )
        else:
            stats["competitions_existing"] += 1

        home_data = data.get("homeTeam", {}) or {}
        away_data = data.get("awayTeam", {}) or {}
        season_data = data.get("season", {}) or {}
        season_str = (season_data.get("startDate", "") or "")[:4] or ""

        home, home_created = ensure_team(
            home_data, competition, season_str,
            client=client, enrich=enrich
        )
        away, away_created = ensure_team(
            away_data, competition, season_str,
            client=client, enrich=enrich
        )
        if home is None or away is None:
            return

        for team, created in [(home, home_created), (away, away_created)]:
            if created:
                stats["teams_new"] += 1
                self.stdout.write(
                    f"  + Equipo: {team.name} (Elo inicial {team.elo:.0f})"
                )
            else:
                stats["teams_existing"] += 1

        match, created = save_match(data, competition, home, away)
        if match is None:
            return

        if created:
            stats["matches_new"] += 1
            self.stdout.write(f"  + Partido: {match}")
        else:
            stats["matches_updated"] += 1
            self.stdout.write(f"  ~ Partido: {match}")

        if not no_elo and match.is_finished and match.has_result \
                and not match.elo_processed:
            try:
                result = apply_elo_update(match)
                if result is not None:
                    stats["elo_processed"] += 1
                    self.stdout.write(
                        f"    Elo: {home.name} {result['home_elo_new']:.0f} | "
                        f"{away.name} {result['away_elo_new']:.0f}"
                    )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"    Error Elo en partido {match.id_api}: {exc}"
                ))

        if not no_forecasts and match.is_scheduled:
            try:
                forecast = generate_forecast(match)
                if forecast is not None:
                    stats["forecasts_generated"] += 1
                    if forecast.is_fallback:
                        stats["forecasts_fallback"] += 1
                    tag = " (fallback)" if forecast.is_fallback else ""
                    self.stdout.write(
                        f"    Pronóstico{tag}: "
                        f"{forecast.prob_home_win:.0%} / "
                        f"{forecast.prob_draw:.0%} / "
                        f"{forecast.prob_away_win:.0%}  "
                        f"(xG {forecast.xg_home:.2f}-{forecast.xg_away:.2f})"
                    )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"    Error pronóstico en partido {match.id_api}: {exc}"
                ))

    def _print_summary(self, stats, date_str):
        self.stdout.write(self.style.SUCCESS(
            f"\nResumen para {date_str}:\n"
            f"  Partidos: {stats['matches_new']} nuevos, "
            f"{stats['matches_updated']} actualizados\n"
            f"  Equipos: {stats['teams_new']} nuevos, "
            f"{stats['teams_existing']} existentes\n"
            f"  Competiciones: {stats['competitions_new']} nuevas, "
            f"{stats['competitions_existing']} existentes\n"
            f"  Elo procesado: {stats['elo_processed']}\n"
            f"  Pronósticos: {stats['forecasts_generated']} generados "
            f"({stats['forecasts_fallback']} fallback solo Elo)\n"
            f"  Errores: {stats['errors']}"
        ))

from datetime import datetime

from django.core.management.base import BaseCommand

from validation.selectors import finished_with_forecast_qs
from validation.services import (
    evaluate_match,
    refresh_calibration_bins,
)


class Command(BaseCommand):
    help = (
        "Evalúa pronósticos de partidos finalizados (Log Loss, Brier, RPS, "
        "MAE de λ, hit de marcador) y reconstruye los bins de calibración. "
        "Idempotente: por defecto solo procesa partidos sin evaluación; "
        "use --rebuild para recalcular todo el rango."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from", dest="date_from", help="Fecha inicial YYYY-MM-DD (inclusive)."
        )
        parser.add_argument(
            "--to", dest="date_to", help="Fecha final YYYY-MM-DD (inclusive)."
        )
        parser.add_argument("--season", help="Temporada (ej. 2024).")
        parser.add_argument("--competition", help="Código de competición (ej. PL).")
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help="Recalcula evaluaciones existentes en el rango.",
        )
        parser.add_argument(
            "--no-calibration",
            action="store_true",
            help="No reconstruye los bins de calibración.",
        )
        parser.add_argument(
            "--limit", type=int, help="Número máximo de partidos a evaluar."
        )

    def handle(self, *args, **options):
        date_from = options.get("date_from")
        date_to = options.get("date_to")
        season = options.get("season")
        competition_code = options.get("competition")
        rebuild = options.get("rebuild", False)
        no_calibration = options.get("no_calibration", False)
        limit = options.get("limit")

        qs = finished_with_forecast_qs(
            date_from=date_from,
            date_to=date_to,
            season=season,
            competition_code=competition_code,
        )
        if not rebuild:
            qs = qs.filter(evaluation__isnull=True)

        total = qs.count()
        self.stdout.write(f"Partidos a evaluar: {total}")
        if total == 0:
            self.stdout.write(
                self.style.WARNING(
                    "Nada que hacer. Use --rebuild para recalcular evaluaciones "
                    "existentes o amplíe el rango con --from/--to."
                )
            )
            return

        iterator = qs.iterator()
        if limit:
            iterator = list(qs[:limit])

        created = updated = 0
        for match in iterator:
            result = evaluate_match(match)
            if result is None:
                continue
            _, was_created = result
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Evaluaciones: {created} creadas, {updated} actualizadas"
            )
        )

        if not no_calibration:
            n_bins, w_from, w_to = refresh_calibration_bins(
                date_from=date_from,
                date_to=date_to,
                season=season,
                competition_code=competition_code,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Bins de calibración: {n_bins} calculados "
                    f"ventana {w_from.date()} → {w_to.date()}"
                )
            )


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()

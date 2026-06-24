from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Orquestador diario: refresca competiciones, sincroniza partidos "
        "de la ventana semanal (football-data) y de la ventana diaria "
        "(api-football), procesa Elo de finalizados, genera pronósticos de "
        "programados y poda pronósticos stale. Pensado para ejecutarse una "
        "vez al día vía cron."
    )

    def add_arguments(self, parser):
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
            "--no-competitions",
            action="store_true",
            help="Omitir el refresco de competiciones (football-data).",
        )
        parser.add_argument(
            "--no-af",
            action="store_true",
            help="Omitir la sincronización de API-Football.",
        )
        parser.add_argument(
            "--no-prune",
            action="store_true",
            help="Omitir la poda de pronósticos fuera de ventana.",
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
        days_ahead = options["days_ahead"]
        days_back = options["days_back"]
        no_elo = options["no_elo"]
        no_forecasts = options["no_forecasts"]

        phases = []
        if not options["no_competitions"]:
            phases.append(("sync_competitions", {}))
        phases.append((
            "sync_matches",
            {
                "days_ahead": days_ahead,
                "days_back": days_back,
                "no_elo": no_elo,
                "no_forecasts": no_forecasts,
            },
        ))
        if not options["no_af"]:
            phases.append((
                "sync_af_matches",
                {
                    "no_elo": no_elo,
                    "no_forecasts": no_forecasts,
                },
            ))
        if not options["no_prune"]:
            phases.append(("prune_future_forecasts", {"days": days_ahead}))

        errors = []
        for name, kwargs in phases:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n>> Fase: {name}"))
            try:
                call_command(name, **kwargs)
            except Exception as exc:
                errors.append((name, exc))
                self.stderr.write(self.style.ERROR(
                    f"Error en fase {name}: {exc}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\nResumen daily_update: {len(phases)} fases ejecutadas, "
            f"{len(errors)} errores."
        ))
        if errors:
            for name, exc in errors:
                self.stderr.write(self.style.ERROR(f"  - {name}: {exc}"))
            exit(1)

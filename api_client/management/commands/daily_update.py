from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from api_client.models import ApiResponseCache


class Command(BaseCommand):
    help = (
        "Orquestador diario: refresca partidos de la ventana semanal "
        "(football-data.org /v4/matches con dateFrom/dateTo), procesa Elo "
        "de finalizados, genera pronósticos de programados, poda "
        "pronósticos stale fuera de ventana y purga la caché de la API "
        "vencida. Pensado para ejecutarse una vez al día vía cron."
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
        parser.add_argument(
            "--no-cache-purge",
            action="store_true",
            help="No purgar la caché de respuestas de la API.",
        )

    def handle(self, *args, **options):
        days_ahead = options["days_ahead"]
        days_back = options["days_back"]
        no_elo = options["no_elo"]
        no_forecasts = options["no_forecasts"]

        phases = [
            (
                "sync_matches",
                {
                    "days_ahead": days_ahead,
                    "days_back": days_back,
                    "no_elo": no_elo,
                    "no_forecasts": no_forecasts,
                },
            ),
        ]
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

        # Purge de la caché de respuestas de la API: elimina entradas
        # con fetched_at más viejo que N× el TTL. Evita que ApiResponseCache
        # crezca indefinidamente con respuestas que ya no sirven.
        if not options["no_cache_purge"]:
            ttl = timedelta(minutes=settings.API_CACHE_TTL_MINUTES)
            threshold = timezone.now() - ttl * 3
            purged, _ = ApiResponseCache.objects.filter(
                fetched_at__lt=threshold
            ).delete()
            self.stdout.write(self.style.SUCCESS(
                f"\n>> Purge caché API: {purged} entradas antiguas eliminadas."
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\nResumen daily_update: {len(phases)} fases ejecutadas, "
            f"{len(errors)} errores."
        ))
        if errors:
            for name, exc in errors:
                self.stderr.write(self.style.ERROR(f"  - {name}: {exc}"))
            exit(1)
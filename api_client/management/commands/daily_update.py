from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone

from api_client.models import ApiResponseCache


class Command(BaseCommand):
    help = (
        "Orquestador diario: refresca partidos de la ventana semanal "
        "(football-data.org /v4/matches con dateFrom/dateTo), procesa Elo "
        "de finalizados, genera pronósticos de programados, poda "
        "pronósticos stale fuera de ventana, materializa evaluaciones de "
        "pronósticos finalizados (ForecastEvaluation) y reconstruye la "
        "calibración global cada CALIBRATION_INTERVAL_DAYS. Pensado para "
        "ejecutarse una vez al día vía cron."
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
        parser.add_argument(
            "--no-evaluation",
            action="store_true",
            help="No materializar ForecastEvaluation de partidos finalizados.",
        )
        parser.add_argument(
            "--no-calibration",
            action="store_true",
            help="No reconstruir CalibrationBin incluso si toca por fecha.",
        )
        parser.add_argument(
            "--force-calibration",
            action="store_true",
            help="Fuerza la reconstrucción de CalibrationBin sin importar el deadline.",
        )

    def handle(self, *args, **options):
        days_ahead = options["days_ahead"]
        days_back = options["days_back"]
        no_elo = options["no_elo"]
        no_forecasts = options["no_forecasts"]

        # Fases delegadas a sub-comandos (heredan try/except en el loop).
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
        if not options["no_evaluation"]:
            # Incremental: solo partidos con Forecast y sin ForecastEvaluation.
            # --no-calibration SIEMPRE: la calibración se maneja como fase
            # propia del orquestador (evita el early-return del sub-comando
            # cuando no hay partidos nuevos que evaluar).
            phases.append(("evaluate_forecasts", {"no_calibration": True}))

        errors = []
        for name, kwargs in phases:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n>> Fase: {name}"))
            try:
                call_command(name, **kwargs)
            except Exception as exc:
                errors.append((name, exc))
                self.stderr.write(self.style.ERROR(f"Error en fase {name}: {exc}"))

        # Fase de calibración: reconstrucción periódica del snapshot global
        # de CalibrationBin. Se hace aparte y no viaja por el sub-comando
        # evaluate_forecasts porque ese sub-comando hace early-return si no
        # hay partidos nuevos, dejando la calibración sin refrescar.
        if not options["no_calibration"]:
            self._run_calibration(force=options["force_calibration"], errors=errors)

        # Purge de la caché de respuestas de la API: elimina entradas
        # con fetched_at más viejo que N× el TTL. Evita que ApiResponseCache
        # crezca indefinidamente con respuestas que ya no sirven.
        if not options["no_cache_purge"]:
            ttl = timedelta(minutes=settings.API_CACHE_TTL_MINUTES)
            threshold = timezone.now() - ttl * 3
            purged, _ = ApiResponseCache.objects.filter(
                fetched_at__lt=threshold
            ).delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n>> Purge caché API: {purged} entradas antiguas eliminadas."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nResumen daily_update: {len(phases)} fases ejecutadas, "
                f"{len(errors)} errores."
            )
        )
        if errors:
            for name, exc in errors:
                self.stderr.write(self.style.ERROR(f"  - {name}: {exc}"))
            exit(1)

    def _run_calibration(self, force=False, errors=None):
        """Reconstruye la calibración si pasó CALIBRATION_INTERVAL_DAYS
        desde el último snapshot (o si --force-calibration).

        Usa CalibrationSnapshot.snapshot_at como sentinel: cualquier
        refresh manual intermedio (evaluate_forecasts --rebuild)
        reinicia el contador automáticamente. Cada refresh crea un
        nuevo snapshot histórico (no sobrescribe el anterior).
        """
        from validation.models import CalibrationSnapshot
        from validation.services import refresh_calibration_bins

        self.stdout.write(self.style.MIGRATE_HEADING("\n>> Fase: calibrate"))
        interval = getattr(settings, "CALIBRATION_INTERVAL_DAYS", 30)
        today = timezone.localdate()

        last_at = CalibrationSnapshot.objects.aggregate(
            last=Max("snapshot_at")
        )["last"]

        if last_at is not None:
            last_date = last_at.date()
            next_due = last_date + timedelta(days=interval)
        else:
            last_date = None
            next_due = today  # sin snapshot previo → calibrar ahora

        if force:
            reason = "forzado por --force-calibration"
            should = True
        elif last_date is None:
            reason = "sin snapshot previo"
            should = True
        elif last_date < today - timedelta(days=interval):
            reason = f"última calibración {last_date} superó {interval} días"
            should = True
        else:
            reason = None
            should = False

        if not should:
            self.stdout.write(
                f"Última calibración: {last_date}; próxima ~{next_due}. Saltada."
            )
            return

        try:
            trigger = (
                CalibrationSnapshot.Trigger.FORCE
                if force
                else CalibrationSnapshot.Trigger.DAILY
            )
            self.stdout.write(f"Refrescando calibración ({reason})...")
            snapshot, n_bins, w_from, w_to = refresh_calibration_bins(trigger=trigger)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Snapshot #{snapshot.id} ({trigger}): {n_bins} bins "
                    f"ventana {w_from.date()} → {w_to.date()} "
                    f"n={snapshot.n} LogLoss={snapshot.log_loss_1x2:.3f}"
                )
            )
        except Exception as exc:
            errors.append(("calibrate", exc))
            self.stderr.write(self.style.ERROR(f"Error en fase calibrate: {exc}"))

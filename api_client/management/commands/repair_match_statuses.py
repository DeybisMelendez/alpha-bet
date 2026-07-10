"""Repara inconsistencias de status/status_short heredadas del mapeo
anterior de football-data.org (docs/api_football.md §Ventana histórica).

Antes, STATUS_MAP no incluía "AWARDED" (caía a SCHEDULED) y colapsaba
"TIMED" en SCHEDULED; además _map_duration defaulteaba a "FT" aunque el
partido no estuviera finalizado. Esto producía:

  1. Partidos con status=SCHEDULED pero marcador asignado (AWARDED real).
  2. Partidos no finalizados con status_short="FT" (debería ser "").

El comando es idempotente: solo reclasifica filas que cumplan las
condiciones; las ya correctas se ignoran.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from matches.models import Match


NON_FINAL_STATES = (
    Match.Status.SCHEDULED,
    Match.Status.TIMED,
    Match.Status.POSTPONED,
    Match.Status.CANCELLED,
    Match.Status.SUSPENDED,
    Match.Status.PAUSED,
    Match.Status.IN_PLAY,
)


class Command(BaseCommand):
    help = (
        "Reclasifica partidos mal mapeados: SCHEDULED con marcador → "
        "AWARDED, y limpia status_short='FT' en no-finalizados."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostrar qué se repararía sin realizar cambios.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        # 1. SCHEDULED con marcador asignado → AWARDED.
        awarded_qs = (
            Match.objects.filter(status=Match.Status.SCHEDULED)
            .exclude(home_goals__isnull=True)
            .exclude(away_goals__isnull=True)
        )
        awarded_count = awarded_qs.count()

        self.stdout.write(
            f"Partidos SCHEDULED con marcador → AWARDED: {awarded_count}"
        )
        if not dry_run and awarded_count:
            for m in awarded_qs:
                self.stdout.write(
                    f"  {m.competition.code} {m.season} {m.utc_date.date()} "
                    f"{m.home_team} vs {m.away_team} {m.home_goals}-"
                    f"{m.away_goals}"
                )
            awarded_qs.update(status=Match.Status.AWARDED)

        # 2. No-finalizados con status_short="FT" → "".
        short_qs = Match.objects.filter(
            status__in=NON_FINAL_STATES,
            status_short="FT",
        )
        short_count = short_qs.count()

        self.stdout.write(
            f"No-finalizados con status_short='FT' → '': {short_count}"
        )
        if not dry_run and short_count:
            short_qs.update(status_short="")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Modo dry-run: no se realizaron cambios."
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Reparación completada: {awarded_count} → AWARDED, "
            f"{short_count} status_short limpiados."
        ))
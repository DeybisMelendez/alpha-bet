from django.db import models

from teams.models import Competition


class ApiResponseCache(models.Model):
    url = models.URLField(unique=True)
    body = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["fetched_at"]),
        ]
        verbose_name = "Caché API"
        verbose_name_plural = "Cachés API"

    def __str__(self):
        return f"{self.url[:80]} @ {self.fetched_at:%Y-%m-%d %H:%M}"


class BackfillJob(models.Model):
    """Cola persistente de backfill histórico (liga × temporada).

    Permite cargar el historial por partes respetando el presupuesto diario
    de la API. El comando load_history lee el siguiente PENDING, lo procesa
    y lo marca DONE. Idempotente: reanudable tras interrupciones.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        IN_PROGRESS = "IN_PROGRESS", "En progreso"
        DONE = "DONE", "Completado"
        EMPTY = "EMPTY", "Sin partidos"
        ERROR = "ERROR", "Error"

    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="backfill_jobs"
    )
    season = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )
    fixtures_count = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    error_msg = models.TextField(blank=True, default="")

    class Meta:
        unique_together = ("competition", "season")
        ordering = ["competition__id_api", "season"]
        verbose_name = "Trabajo de backfill"
        verbose_name_plural = "Trabajos de backfill"

    def __str__(self):
        return f"{self.competition.code} {self.season} [{self.status}]"
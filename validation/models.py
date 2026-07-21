from django.db import models
from django.utils import timezone

from matches.models import Match


class ForecastEvaluation(models.Model):
    """Evaluación post-partido de un pronóstico persistido.

    1:1 con Match (partidos finalizados con Forecast existente). Copia de
    los goles reales y métricas de error de los mercados 1X2 + λ. Las
    métricas se calculan con funciones puras en validation/metrics.py para
    facilitar tests y reusabilidad.
    """

    match = models.OneToOneField(
        Match, on_delete=models.CASCADE, related_name="evaluation"
    )
    # Snapshot de goles reales (copia defensiva para auditoría histórica,
    # por si el partido se reimportara con corrección de marcador).
    actual_home_goals = models.PositiveSmallIntegerField()
    actual_away_goals = models.PositiveSmallIntegerField()
    actual_outcome = models.CharField(
        max_length=1,
        help_text="1 (local), X (empate) o 2 (visitante). PEN cuenta como empate.",
    )

    # Métricas 1X2. Probabilidad pronosticada del evento que ocurrió
    # (P_1, P_X o P_2) → Log Loss = -log(p_actual). Brier multi-clase =
    # Σ (p_i − 1{i=actual})². RPS = Ranked Probability Score para 1X2.
    log_loss_1x2 = models.FloatField()
    brier_1x2 = models.FloatField()
    rps_1x2 = models.FloatField()

    # Métricas de λ (goles esperados). Error absoluto por equipo y total.
    ae_xg_home = models.FloatField()
    ae_xg_away = models.FloatField()
    ae_total = models.FloatField(
        help_text="|xg_home + xg_away − goles_totales|.",
    )

    # Extra barato: puntaje de marcador más probable predicho por el
    # Forecast (top_score) contra el marcador real.
    top_score_hit = models.BooleanField(default=False)

    # Copia de temporada/competición para filtrar rápido sin joins.
    season = models.CharField(max_length=20, blank=True, default="", db_index=True)
    competition = models.ForeignKey(
        "teams.Competition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forecast_evaluations",
    )
    is_fallback = models.BooleanField(
        default=False,
        help_text="True si el Forecast evaluado era fallback solo Elo.",
    )
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-match__utc_date"]
        indexes = [
            models.Index(fields=["season"]),
            models.Index(fields=["competition", "season"]),
        ]
        verbose_name = "Evaluación"
        verbose_name_plural = "Evaluaciones"

    def __str__(self):
        return f"Evaluación {self.match}"


class CalibrationSnapshot(models.Model):
    """Snapshot histórico de calibración + KPIs en un momento dado.

    Cada ejecución de `evaluate_forecasts` (o la fase de calibración del
    `daily_update`) crea un nuevo snapshot en vez de sobrescribir el
    anterior, de modo que se pueda seguir la evolución del modelo en el
    tiempo. Los `CalibrationBin` individuales cuelgan de un snapshot
    concreto vía FK, y los KPIs agregados se denormalizan aquí para no
    tener que recalcularlos al dibujar la serie temporal.

    Política de retención: no se borran snapshots (volumen despreciable,
    ~12 snapshots/año × 30 bins). Si en el futuro se quiere purgar, irá
    en un comando aparte.
    """

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual (evaluate_forecasts)"
        REBUILD = "rebuild", "Rebuild (--rebuild)"
        DAILY = "daily", "Daily update"
        FORCE = "force", "Force (--force-calibration)"
        LEGACY = "legacy", "Legacy (migración)"

    snapshot_at = models.DateTimeField(default=timezone.now, db_index=True)
    window_from = models.DateTimeField(null=True, blank=True)
    window_to = models.DateTimeField(null=True, blank=True)
    n = models.PositiveIntegerField(default=0)

    # KPIs denormalizados (copia de aggregate_kpis en el momento del snapshot).
    log_loss_1x2 = models.FloatField(default=0.0)
    brier_1x2 = models.FloatField(default=0.0)
    rps_1x2 = models.FloatField(default=0.0)
    ae_xg_home = models.FloatField(default=0.0)
    ae_xg_away = models.FloatField(default=0.0)
    ae_total = models.FloatField(default=0.0)
    top_score_hit_ratio = models.FloatField(default=0.0)

    trigger = models.CharField(
        max_length=10, choices=Trigger.choices, default=Trigger.MANUAL
    )
    season = models.CharField(max_length=20, blank=True, default="")
    competition = models.ForeignKey(
        "teams.Competition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calibration_snapshots",
    )

    class Meta:
        ordering = ["-snapshot_at"]
        indexes = [
            models.Index(fields=["snapshot_at"]),
            models.Index(fields=["season", "competition"]),
        ]
        verbose_name = "Snapshot de calibración"
        verbose_name_plural = "Snapshots de calibración"

    def __str__(self):
        return f"Snapshot {self.snapshot_at:%Y-%m-%d %H:%M} (n={self.n})"


class CalibrationBin(models.Model):
    """Bin de calibración: frecuencia observada vs promedio pronosticado.

    Una fila por (snapshot, mercado, bin de probabilidad). Los bins
    cuelgan de un `CalibrationSnapshot` que captura el momento exacto del
    refresh, permitiendo reconstruir la curva de calibración histórica.
    Sirve para detectar sesgos: si el modelo dice "P=0.4" para un outcome
    y ocurre el 30% de las veces, el modelo está sobreconfiado en ese bin.
    """

    class Market(models.TextChoices):
        HOME_WIN = "1X2_HOME", "Local (1X2)"
        DRAW = "1X2_DRAW", "Empate (1X2)"
        AWAY_WIN = "1X2_AWAY", "Visitante (1X2)"

    snapshot = models.ForeignKey(
        CalibrationSnapshot,
        on_delete=models.CASCADE,
        related_name="bins",
        null=True,
        help_text="Snapshot al que pertenece el bin. Null solo durante migraciones.",
    )
    market = models.CharField(max_length=20, choices=Market.choices)
    bin_start = models.FloatField()  # Inclusivo, p. ej. 0.0
    bin_end = models.FloatField()  # Exclusivo, p. ej. 0.1 (excepto el último = 1.0)
    count = models.PositiveIntegerField(default=0)
    predicted_avg = models.FloatField(
        default=0.0,
        help_text="Promedio de probabilidad pronosticada en el bin.",
    )
    observed_freq = models.FloatField(
        default=0.0,
        help_text="Fracción real que ocurrió en el bin (0..1).",
    )

    class Meta:
        unique_together = ("snapshot", "market", "bin_start")
        ordering = ["market", "bin_start"]
        verbose_name = "Bin de calibración"
        verbose_name_plural = "Bins de calibración"

    def __str__(self):
        return f"{self.market} [{self.bin_start:.2f},{self.bin_end:.2f})"

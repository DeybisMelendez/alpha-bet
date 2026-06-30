from django.db import models

from teams.models import Competition, Team


class Match(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Programado"
        TIMED = "TIMED", "Timed"
        IN_PLAY = "IN_PLAY", "En juego"
        PAUSED = "PAUSED", "Pausado"
        FINISHED = "FINISHED", "Finalizado"
        SUSPENDED = "SUSPENDED", "Suspendido"
        POSTPONED = "POSTPONED", "Aplazado"
        CANCELLED = "CANCELLED", "Cancelado"
        AWARDED = "AWARDED", "Adjudicado"

    id_api = models.PositiveIntegerField(unique=True, db_index=True)
    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="matches"
    )
    season = models.CharField(max_length=20, blank=True, default="")
    round = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Ronda/jornada de API-Football (league.round).",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    # Status original de API-Football (FT, AET, PEN, NS, etc.). Se conserva
    # aparte del status normalizado para que el motor de Elo pueda distinguir
    # partidos decididos por penales (PEN) y tratarlos como empate.
    status_short = models.CharField(
        max_length=10, blank=True, default="",
        help_text="Status corto de API-Football (FT, AET, PEN, ...).",
    )
    utc_date = models.DateTimeField()

    # Sede neutral (Mundial, fases finales internacionales, partidos
    # en campo neutral). Documentado en docs/elo.md: cuando True la
    # localía no aplica en el cálculo de Elo.
    is_neutral = models.BooleanField(
        default=False,
        help_text="Sede neutral: la localía no aplica en Elo.",
    )
    venue = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Estadio donde se disputa el partido (por partido).",
    )
    referee = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Árbitro del partido.",
    )
    # Importancia competitiva derivada de la competición y la ronda.
    # Se infiere al importar (api_client/sync.py) y permite ajustar
    # modelos secundarios futuros.
    class Importance(models.TextChoices):
        FRIENDLY = "FRIENDLY", "Amistoso"
        LEAGUE = "LEAGUE", "Liga"
        CUP = "CUP", "Copa"
        KNOCKOUT = "KNOCKOUT", "Eliminatoria"
        INTERNATIONAL = "INTERNATIONAL", "Internacional"
    importance = models.CharField(
        max_length=20,
        choices=Importance.choices,
        default=Importance.LEAGUE,
    )
    # Días de descanso desde el último partido finalizado de cada
    # equipo. Se calcula al importar; nullable para no bloquear el
    # backfill si todavía no hay historial.
    rest_days_home = models.PositiveSmallIntegerField(null=True, blank=True)
    rest_days_away = models.PositiveSmallIntegerField(null=True, blank=True)

    home_team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="home_matches"
    )
    away_team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="away_matches"
    )

    home_goals = models.PositiveIntegerField(null=True, blank=True)
    away_goals = models.PositiveIntegerField(null=True, blank=True)

    elo_processed = models.BooleanField(default=False)
    home_elo_before = models.FloatField(null=True, blank=True)
    away_elo_before = models.FloatField(null=True, blank=True)
    home_elo_after = models.FloatField(null=True, blank=True)
    away_elo_after = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-utc_date"]
        indexes = [
            models.Index(fields=["status", "utc_date"]),
            models.Index(fields=["elo_processed"]),
            models.Index(fields=["competition", "season"]),
        ]
        verbose_name = "Partido"
        verbose_name_plural = "Partidos"

    def __str__(self):
        date_str = (
            self.utc_date.date().isoformat()
            if hasattr(self.utc_date, "date")
            else str(self.utc_date)[:10]
        )
        return f"{self.home_team.name} vs {self.away_team.name} ({date_str})"

    @property
    def is_finished(self):
        return self.status in (self.Status.FINISHED, self.Status.AWARDED)

    @property
    def is_scheduled(self):
        return self.status in (self.Status.SCHEDULED, self.Status.TIMED)

    @property
    def has_result(self):
        return self.home_goals is not None and self.away_goals is not None

    @property
    def goal_diff(self):
        if not self.has_result:
            return 0
        return abs(self.home_goals - self.away_goals)
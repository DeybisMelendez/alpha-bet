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

    class Source(models.TextChoices):
        FOOTBALLDATA = "footballdata", "football-data.org"
        APIFOOTBALL = "apifootball", "API-Football"

    id_api = models.PositiveIntegerField(db_index=True)
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.FOOTBALLDATA
    )
    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="matches"
    )
    season = models.CharField(max_length=20, blank=True, default="")
    matchday = models.PositiveIntegerField(null=True, blank=True)
    stage = models.CharField(max_length=50, blank=True, default="")
    group = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    utc_date = models.DateTimeField()

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
        unique_together = ("id_api", "source")
        ordering = ["-utc_date"]
        indexes = [
            models.Index(fields=["status", "utc_date"]),
            models.Index(fields=["elo_processed"]),
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

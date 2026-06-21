from django.db import models

from matches.models import Match
from teams.models import Competition, Team


class LeagueStrength(models.Model):
    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="strengths"
    )
    season = models.CharField(max_length=20)
    average_elo = models.FloatField(default=1500.0)

    class Meta:
        unique_together = ("competition", "season")
        verbose_name = "Fuerza de Liga"
        verbose_name_plural = "Fuerza de Ligas"

    def __str__(self):
        return f"{self.competition.code} {self.season} - Elo {self.average_elo:.0f}"


class EloLog(models.Model):
    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="elo_logs"
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="elo_logs"
    )
    elo_before = models.FloatField()
    elo_after = models.FloatField()
    delta = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Log Elo"
        verbose_name_plural = "Logs Elo"

    def __str__(self):
        return f"{self.team.name} {self.elo_before:.0f} -> {self.elo_after:.0f}"

from django.db import models

from matches.models import Match


class Forecast(models.Model):
    match = models.OneToOneField(
        Match, on_delete=models.CASCADE, related_name="forecast"
    )
    xg_home = models.FloatField()
    xg_away = models.FloatField()
    prob_home_win = models.FloatField()
    prob_draw = models.FloatField()
    prob_away_win = models.FloatField()
    form_home = models.JSONField(default=dict, blank=True)
    form_away = models.JSONField(default=dict, blank=True)
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-match__utc_date"]
        verbose_name = "Pronóstico"
        verbose_name_plural = "Pronósticos"

    def __str__(self):
        return f"Pronóstico {self.match}"

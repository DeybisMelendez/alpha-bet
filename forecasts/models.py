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

    # Mercados de goles derivados de la matriz Poisson (docs/pronostico.md).
    # Over/Under x.5 (P(total > x)). BTTS / BTTS no.
    prob_over_05 = models.FloatField(default=0.0)
    prob_over_15 = models.FloatField(default=0.0)
    prob_over_25 = models.FloatField(default=0.0)
    prob_over_35 = models.FloatField(default=0.0)
    prob_over_45 = models.FloatField(default=0.0)
    prob_btts = models.FloatField(default=0.0)
    prob_btts_no = models.FloatField(default=0.0)
    # Probabilidad de marcar al menos un gol (P(team >= 1)).
    prob_score_home = models.FloatField(default=0.0)
    prob_score_home_no = models.FloatField(default=0.0)
    prob_score_away = models.FloatField(default=0.0)
    prob_score_away_no = models.FloatField(default=0.0)
    # Doble oportunidad.
    prob_1x = models.FloatField(default=0.0)
    prob_x2 = models.FloatField(default=0.0)
    prob_12 = models.FloatField(default=0.0)
    # Draw No Bet (DNB): empate devuelve la apuesta.
    prob_dnb_home = models.FloatField(default=0.0)
    prob_dnb_away = models.FloatField(default=0.0)

    # Marcador correcto más probable (top). score = "i-j".
    top_score = models.CharField(max_length=10, blank=True, default="")
    top_score_prob = models.FloatField(default=0.0)

    form_home = models.JSONField(default=dict, blank=True)
    form_away = models.JSONField(default=dict, blank=True)
    is_fallback = models.BooleanField(
        default=False,
        help_text=(
            "True si se calculó solo con Elo (sin historial suficiente de "
            "forma reciente)."
        ),
    )
    pending_prior_match = models.BooleanField(
        default=False,
        help_text=(
            "True si alguno de los dos equipos tiene un partido previo "
            "programado todavía no finalizado. El pronóstico se "
            "actualizará automáticamente al finalizar dicho partido."
        ),
    )
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-match__utc_date"]
        verbose_name = "Pronóstico"
        verbose_name_plural = "Pronósticos"

    def __str__(self):
        return f"Pronóstico {self.match}"
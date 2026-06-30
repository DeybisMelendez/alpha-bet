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
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-match__utc_date"]
        verbose_name = "Pronóstico"
        verbose_name_plural = "Pronósticos"

    def __str__(self):
        return f"Pronóstico {self.match}"


class MarketForecast(models.Model):
    """Pronóstico de un mercado secundario (remates, córners, tarjetas,
    faltas) asociado a un Forecast.

    Un mercado se describe por (market, selection, lambda) y sus
    probabilidades derivadas. Por ejemplo:
      market=shots, selection=over_2_5, prob=0.61
      market=corners, selection=home, prob=0.44
    Almacenar aquí (en vez de columnas en Forecast) permite añadir
    mercados nuevos sin migrar el schema cada vez.
    """

    class Market(models.TextChoices):
        SHOTS = "SHOTS", "Remates"
        SHOTS_ON_GOAL = "SHOTS_ON_GOAL", "Remates al arco"
        CORNERS = "CORNERS", "Córners"
        CARDS = "CARDS", "Tarjetas"
        FOULS = "FOULS", "Faltas"
        GOALS = "GOALS", "Goles"

    forecast = models.ForeignKey(
        Forecast, on_delete=models.CASCADE, related_name="markets"
    )
    market = models.CharField(max_length=20, choices=Market.choices)
    # Lambda esperado delevento bajo Poisson (total o por equipo).
    lam = models.FloatField(default=0.0)
    # Selección del mercado (libre: "total_over_2_5", "home", "away",
    # "match_total", etc.). Las claves dependen del mercado.
    selection = models.CharField(max_length=40)
    prob = models.FloatField(default=0.0)
    label = models.CharField(max_length=100, blank=True, default="")
    is_fallback = models.BooleanField(default=False)

    class Meta:
        unique_together = ("forecast", "market", "selection")
        ordering = ["market", "selection"]
        verbose_name = "Mercado secundario"
        verbose_name_plural = "Mercados secundarios"

    def __str__(self):
        return f"{self.get_market_display()} {self.selection} ({self.prob:.2f})"
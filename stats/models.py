from django.db import models

from matches.models import Match
from teams.models import Team


class MatchStatistics(models.Model):
    """Estadísticas de un partido finalizado, por equipo.

    Fuente: API-Football /fixtures/statistics (remates, posesión,
    córners, faltas, tarjetas) y /fixtures/events (goles por tiempo,
    tarjetas individuales cuando se requieran).

    Se almacena aparte de Match para no sobrecargar el modelo principal
    y porque las stats solo existen una vez finalizado el partido. Sirve
    de base para los modelos de mercados secundarios (remates, córners,
    tarjetas, faltas) y para futuros promedios móviles precalculados.
    """

    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="statistics"
    )
    # Equipo al que corresponden estas stats (un registro por equipo y
    # partido). La PK garantiza unicidad vía (match, team).
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="match_statistics"
    )
    is_home = models.BooleanField(default=False)

    # Goles por tiempo (según api.md). fulltime ya vive en Match.
    goals_first_half = models.PositiveSmallIntegerField(null=True, blank=True)
    goals_second_half = models.PositiveSmallIntegerField(null=True, blank=True)

    # Remates.
    shots_total = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_on_goal = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_off_goal = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_blocked = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_inside_box = models.PositiveSmallIntegerField(null=True, blank=True)
    shots_outside_box = models.PositiveSmallIntegerField(null=True, blank=True)

    # Posesión (porcentaje 0-100).
    possession = models.FloatField(null=True, blank=True)

    # Ataque.
    corners = models.PositiveSmallIntegerField(null=True, blank=True)
    offsides = models.PositiveSmallIntegerField(null=True, blank=True)

    # Disciplina.
    fouls_committed = models.PositiveSmallIntegerField(null=True, blank=True)
    yellow_cards = models.PositiveSmallIntegerField(null=True, blank=True)
    red_cards = models.PositiveSmallIntegerField(null=True, blank=True)

    # Portería.
    goalkeeper_saves = models.PositiveSmallIntegerField(null=True, blank=True)

    # Pases (cuando la competición lo proporcione).
    passes_total = models.PositiveIntegerField(null=True, blank=True)
    passes_accurate = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("match", "team")
        ordering = ["-match__utc_date"]
        verbose_name = "Estadística de partido"
        verbose_name_plural = "Estadísticas de partidos"

    def __str__(self):
        return f"{self.team.name} @ {self.match}"
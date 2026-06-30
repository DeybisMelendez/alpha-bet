from django.db import models


class Competition(models.Model):
    class Kind(models.TextChoices):
        LEAGUE = "LEAGUE", "Liga"
        CUP = "CUP", "Copa nacional"
        CONTINENTAL = "CONTINENTAL", "Copa continental"
        INTERNATIONAL = "INTERNATIONAL", "Torneo de selecciones"
        WORLD_CUP = "WORLD_CUP", "Mundial"
        QUALIFIERS = "QUALIFIERS", "Eliminatorias"
        FRIENDLY = "FRIENDLY", "Amistoso"
        OTHER = "OTHER", "Otra"

    id_api = models.PositiveIntegerField(unique=True, db_index=True)
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    area_name = models.CharField(max_length=100, blank=True, default="")
    area_code = models.CharField(max_length=20, blank=True, default="")
    league_type = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Tipo de competición según API-Football (league/cup).",
    )
    logo = models.URLField(blank=True, default="")
    current_season = models.CharField(max_length=20, blank=True, default="")
    # Clasificación del nivel competitivo. Implica K-factor (docs/elo.md:
    # Mundial 30, Eliminatorias 25, Liga/Copa nacional 20, Amistoso 15)
    # y localía por competición (nacional +70-90, selecciones +50-80,
    # neutral 0). Se infiere al importar.
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.LEAGUE,
    )
    # Ventaja de localía en puntos Elo para esta competición. docs/elo.md:
    # liga nacional 70-90, selecciones 50-80, Mundial/neutral 0.
    home_advantage = models.PositiveSmallIntegerField(default=80)

    class Meta:
        ordering = ["name"]
        verbose_name = "Competición"
        verbose_name_plural = "Competiciones"

    def __str__(self):
        return self.name


class Team(models.Model):
    id_api = models.PositiveIntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=200)
    tla = models.CharField(max_length=10, blank=True, default="")
    crest_url = models.URLField(blank=True, default="")
    founded = models.PositiveIntegerField(null=True, blank=True)
    venue = models.CharField(max_length=200, blank=True, default="")
    country = models.CharField(max_length=100, blank=True, default="")
    elo = models.FloatField(default=1500.0)
    matches_played = models.PositiveIntegerField(default=0)
    # Temporada hasta la cual se ha aplicado la regresión Elo docs/elo.md
    # (0.90·Elo + 0.10·EloLiga). Permite ejecutar regress_elo por temporada
    # de forma idempotente.
    last_regressed_season = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        ordering = ["name"]
        verbose_name = "Equipo"
        verbose_name_plural = "Equipos"

    def __str__(self):
        return self.name


class TeamCompetition(models.Model):
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="competition_links"
    )
    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="team_links"
    )
    season = models.CharField(max_length=20)

    class Meta:
        unique_together = ("team", "competition", "season")
        verbose_name = "Equipo-Competición"
        verbose_name_plural = "Equipos-Competiciones"

    def __str__(self):
        return f"{self.team.name} - {self.competition.code} {self.season}"
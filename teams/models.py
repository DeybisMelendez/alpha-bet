from django.db import models


class Competition(models.Model):
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
from django.contrib import admin

from matches.models import Match


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "id_api",
        "competition",
        "home_team",
        "away_team",
        "utc_date",
        "status",
        "home_goals",
        "away_goals",
        "elo_processed",
    )
    list_filter = ("status", "competition", "elo_processed", "season")
    search_fields = (
        "home_team__name",
        "away_team__name",
        "competition__name",
    )
    date_hierarchy = "utc_date"
    readonly_fields = (
        "elo_processed",
        "home_elo_before",
        "away_elo_before",
        "home_elo_after",
        "away_elo_after",
    )
    ordering = ("-utc_date",)

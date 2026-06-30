from django.contrib import admin

from stats.models import MatchStatistics


@admin.register(MatchStatistics)
class MatchStatisticsAdmin(admin.ModelAdmin):
    list_display = (
        "match_display", "team", "is_home",
        "shots_total", "shots_on_goal", "possession",
        "corners", "yellow_cards", "red_cards", "fouls_committed",
    )
    list_filter = ("is_home", "team__country")
    search_fields = ("team__name", "match__home_team__name", "match__away_team__name")
    ordering = ("-match__utc_date",)
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "match__home_team", "match__away_team", "team"
        )

    def match_display(self, obj):
        return str(obj.match)
    match_display.short_description = "Partido"
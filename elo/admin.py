from django.contrib import admin

from elo.models import EloLog, LeagueStrength


@admin.register(LeagueStrength)
class LeagueStrengthAdmin(admin.ModelAdmin):
    list_display = ("competition", "season", "average_elo")
    list_display_links = ("competition", "season")
    list_filter = ("season", "competition")
    search_fields = ("competition__name", "competition__code")
    ordering = ("-season", "competition")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("competition")

    def average_elo(self, obj):
        return f"{obj.average_elo:.0f}"
    average_elo.short_description = "Elo promedio"


@admin.register(EloLog)
class EloLogAdmin(admin.ModelAdmin):
    list_display = ("team", "match_display", "elo_before", "elo_after", "delta", "created_at")
    list_display_links = ("team",)
    list_filter = ("created_at", "team__competition_links__competition")
    search_fields = ("team__name", "team__tla", "match__home_team__name", "match__away_team__name")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
    list_per_page = 50
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "team", "match__home_team", "match__away_team"
        )

    def match_display(self, obj):
        if obj.match:
            return str(obj.match)
        return "-"
    match_display.short_description = "Partido"

    def delta(self, obj):
        return f"{obj.delta:+.1f}"
    delta.short_description = "Delta"

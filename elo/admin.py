from django.contrib import admin

from elo.models import EloLog, LeagueStrength


@admin.register(LeagueStrength)
class LeagueStrengthAdmin(admin.ModelAdmin):
    list_display = ("competition", "season", "average_elo")
    list_filter = ("season",)
    search_fields = ("competition__name", "competition__code")


@admin.register(EloLog)
class EloLogAdmin(admin.ModelAdmin):
    list_display = ("team", "match", "elo_before", "elo_after", "delta", "created_at")
    list_filter = ("created_at",)
    search_fields = ("team__name",)
    readonly_fields = ("created_at",)

from django.contrib import admin

from forecasts.models import Forecast


@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    list_display = (
        "match",
        "xg_home",
        "xg_away",
        "prob_home_win",
        "prob_draw",
        "prob_away_win",
        "calculated_at",
    )
    list_filter = ("calculated_at", "match__competition")
    search_fields = (
        "match__home_team__name",
        "match__away_team__name",
    )
    readonly_fields = ("calculated_at",)

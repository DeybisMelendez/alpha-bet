from django.contrib import admin

from validation.models import CalibrationBin, ForecastEvaluation


@admin.register(ForecastEvaluation)
class ForecastEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "match",
        "actual_outcome",
        "log_loss_1x2",
        "brier_1x2",
        "rps_1x2",
        "ae_xg_home",
        "ae_xg_away",
        "ae_total",
        "top_score_hit",
        "is_fallback",
        "season",
    )
    list_filter = ("season", "competition", "is_fallback", "actual_outcome")
    search_fields = (
        "match__home_team__name",
        "match__away_team__name",
        "match__competition__name",
    )
    ordering = ("-match__utc_date",)
    readonly_fields = ("evaluated_at",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "match__home_team", "match__away_team", "match__competition"
            )
        )


@admin.register(CalibrationBin)
class CalibrationBinAdmin(admin.ModelAdmin):
    list_display = (
        "market",
        "bin_start",
        "bin_end",
        "count",
        "predicted_avg",
        "observed_freq",
        "window_from",
        "window_to",
    )
    list_filter = ("market",)
    ordering = ("market", "bin_start")

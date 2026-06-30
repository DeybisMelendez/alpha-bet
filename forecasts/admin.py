from django.contrib import admin
from django.utils import timezone
from datetime import timedelta

from forecasts.models import Forecast, MarketForecast


class MarketForecastInline(admin.TabularInline):
    model = MarketForecast
    extra = 0
    readonly_fields = ("selection", "lam", "prob", "label", "is_fallback")
    can_delete = False
    max_num = 0


class ForecastDateFilter(admin.SimpleListFilter):
    title = "Fecha"
    parameter_name = "forecast_date"

    def lookups(self, request, model_admin):
        return (
            ("today", "Hoy"),
            ("yesterday", "Ayer"),
            ("last_7", "Últimos 7 días"),
            ("last_30", "Últimos 30 días"),
        )

    def queryset(self, request, queryset):
        today = timezone.now().date()
        if self.value() == "today":
            return queryset.filter(calculated_at__date=today)
        if self.value() == "yesterday":
            return queryset.filter(calculated_at__date=today - timedelta(days=1))
        if self.value() == "last_7":
            return queryset.filter(calculated_at__date__gte=today - timedelta(days=7))
        if self.value() == "last_30":
            return queryset.filter(calculated_at__date__gte=today - timedelta(days=30))


@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    list_display = (
        "match_display",
        "xg_display",
        "prob_home_win",
        "prob_draw",
        "prob_away_win",
        "top_score",
        "prediction",
        "fallback_display",
        "calculated_at",
    )
    list_display_links = ("match_display",)
    list_filter = (
        ForecastDateFilter, "is_fallback", "match__competition",
        "match__season",
    )
    search_fields = (
        "match__home_team__name",
        "match__away_team__name",
        "match__home_team__tla",
        "match__away_team__tla",
        "match__competition__name",
    )
    ordering = ("-match__utc_date",)
    readonly_fields = ("calculated_at", "form_home", "form_away")
    list_per_page = 50
    date_hierarchy = "calculated_at"
    inlines = (MarketForecastInline,)
    fieldsets = (
        ("Partido", {
            "fields": ("match",),
        }),
        ("Goles esperados", {
            "fields": ("xg_home", "xg_away"),
        }),
        ("Probabilidades 1X2", {
            "fields": ("prob_home_win", "prob_draw", "prob_away_win"),
        }),
        ("Mercados de goles", {
            "fields": (
                "prob_over_05", "prob_over_15", "prob_over_25",
                "prob_over_35", "prob_over_45",
                "prob_btts", "prob_btts_no",
                "prob_score_home", "prob_score_home_no",
                "prob_score_away", "prob_score_away_no",
                "prob_1x", "prob_x2", "prob_12",
                "prob_dnb_home", "prob_dnb_away",
                "top_score", "top_score_prob",
            ),
            "classes": ("collapse",),
        }),
        ("Forma reciente", {
            "fields": ("form_home", "form_away"),
            "classes": ("collapse",),
        }),
        ("Metadatos", {
            "fields": ("calculated_at",),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "match__home_team", "match__away_team", "match__competition"
        )

    def match_display(self, obj):
        m = obj.match
        return f"{m.home_team.name} vs {m.away_team.name} ({m.utc_date.date().isoformat()})"
    match_display.short_description = "Partido"

    def xg_display(self, obj):
        return f"{obj.xg_home:.2f} - {obj.xg_away:.2f}"
    xg_display.short_description = "xG"

    def prediction(self, obj):
        probs = {
            "Local": obj.prob_home_win,
            "Empate": obj.prob_draw,
            "Visitante": obj.prob_away_win,
        }
        return max(probs, key=probs.get)
    prediction.short_description = "Pronóstico"

    def fallback_display(self, obj):
        return "Sí" if obj.is_fallback else "No"
    fallback_display.short_description = "Fallback"


admin.site.register(MarketForecast)
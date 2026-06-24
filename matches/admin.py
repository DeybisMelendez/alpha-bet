from django.contrib import admin

from matches.models import Match


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "utc_date",
        "competition",
        "home_team",
        "score_display",
        "away_team",
        "status",
        "elo_badge",
    )
    list_display_links = ("utc_date", "home_team")
    list_filter = (
        "status",
        "elo_processed",
        "competition",
        "season",
        "stage",
    )
    search_fields = (
        "home_team__name",
        "away_team__name",
        "home_team__tla",
        "away_team__tla",
        "competition__name",
        "competition__code",
        "id_api",
    )
    date_hierarchy = "utc_date"
    ordering = ("-utc_date",)
    list_per_page = 50
    fieldsets = (
        ("Partido", {
            "fields": ("id_api", "competition", "season", "utc_date"),
        }),
        ("Equipos", {
            "fields": ("home_team", "away_team", "home_goals", "away_goals"),
        }),
        ("Detalle", {
            "fields": ("matchday", "stage", "group", "status"),
        }),
        ("Elo", {
            "fields": (
                "elo_processed",
                "home_elo_before", "away_elo_before",
                "home_elo_after", "away_elo_after",
            ),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = (
        "id_api",
        "elo_processed",
        "home_elo_before",
        "away_elo_before",
        "home_elo_after",
        "away_elo_after",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "competition", "home_team", "away_team"
        )

    def score_display(self, obj):
        if obj.home_goals is None or obj.away_goals is None:
            return "-"
        return f"{obj.home_goals} - {obj.away_goals}"
    score_display.short_description = "Resultado"

    def elo_badge(self, obj):
        if not obj.elo_processed and obj.is_finished:
            return "Pendiente"
        if obj.elo_processed:
            return "Procesado"
        return "-"
    elo_badge.short_description = "Elo"

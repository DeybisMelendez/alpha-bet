from django.contrib import admin

from teams.models import Competition, Team, TeamCompetition


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "area_name", "league_type", "current_season", "team_count")
    list_display_links = ("code", "name")
    list_filter = ("league_type", "area_name", "current_season")
    search_fields = ("name", "code", "area_name", "area_code")
    ordering = ("name",)
    fieldsets = (
        (None, {
            "fields": ("id_api", "code", "name", "logo"),
        }),
        ("Ubicación", {
            "fields": ("area_name", "area_code"),
        }),
        ("Configuración", {
            "fields": ("league_type", "current_season"),
        }),
    )
    readonly_fields = ("id_api",)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("team_links")

    def team_count(self, obj):
        return obj.team_links.count()
    team_count.short_description = "Equipos"


class TeamCompetitionInline(admin.TabularInline):
    model = TeamCompetition
    extra = 0
    fields = ("competition", "season")
    readonly_fields = ("competition", "season")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "tla", "elo", "matches_played", "founded", "has_crest")
    list_display_links = ("name", "tla")
    list_filter = ("founded", "competition_links__competition", "competition_links__season")
    search_fields = ("name", "tla", "venue")
    ordering = ("-elo", "name")
    fieldsets = (
        (None, {
            "fields": ("id_api", "name", "tla", "crest_url"),
        }),
        ("Información", {
            "fields": ("founded", "venue", "country"),
        }),
        ("Elo", {
            "fields": ("elo", "matches_played"),
        }),
    )
    readonly_fields = ("id_api",)
    inlines = [TeamCompetitionInline]
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("competition_links")

    def has_crest(self, obj):
        return bool(obj.crest_url)
    has_crest.boolean = True
    has_crest.short_description = "Escudo"


@admin.register(TeamCompetition)
class TeamCompetitionAdmin(admin.ModelAdmin):
    list_display = ("team", "competition", "season")
    list_display_links = ("team",)
    list_filter = ("competition", "season")
    search_fields = ("team__name", "team__tla", "competition__name", "competition__code")
    ordering = ("-season", "competition", "team")
    list_per_page = 50

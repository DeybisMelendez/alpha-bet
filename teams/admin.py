from django.contrib import admin

from teams.models import Competition, Team, TeamCompetition


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ("id_api", "code", "name", "area_name", "current_season")
    list_filter = ("plan", "area_name")
    search_fields = ("name", "code", "area_name")
    ordering = ("name",)


class TeamCompetitionInline(admin.TabularInline):
    model = TeamCompetition
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "id_api",
        "name",
        "tla",
        "elo",
        "matches_played",
        "founded",
    )
    list_filter = ("founded",)
    search_fields = ("name", "short_name", "tla")
    ordering = ("-elo", "name")
    inlines = [TeamCompetitionInline]


@admin.register(TeamCompetition)
class TeamCompetitionAdmin(admin.ModelAdmin):
    list_display = ("team", "competition", "season")
    list_filter = ("competition", "season")
    search_fields = ("team__name", "competition__name")

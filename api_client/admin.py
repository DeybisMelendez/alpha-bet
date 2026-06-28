from django.contrib import admin

from api_client.models import ApiResponseCache, BackfillJob


@admin.register(ApiResponseCache)
class ApiResponseCacheAdmin(admin.ModelAdmin):
    list_display = ("endpoint", "fetched_at", "age_minutes")
    list_display_links = ("endpoint",)
    list_filter = ("fetched_at",)
    search_fields = ("url",)
    readonly_fields = ("fetched_at", "url", "body")
    ordering = ("-fetched_at",)
    list_per_page = 50

    def endpoint(self, obj):
        url = obj.url
        prefix = "https://v3.football.api-sports.io"
        if url.startswith(prefix):
            return url[len(prefix):]
        return url
    endpoint.short_description = "Endpoint"

    def age_minutes(self, obj):
        from django.utils import timezone
        delta = timezone.now() - obj.fetched_at
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes} min"
    age_minutes.short_description = "Antigüedad"


@admin.register(BackfillJob)
class BackfillJobAdmin(admin.ModelAdmin):
    list_display = (
        "competition", "season", "status", "fixtures_count", "last_run_at",
    )
    list_display_links = ("competition", "season")
    list_filter = ("status", "competition")
    search_fields = ("competition__name", "competition__code", "season")
    ordering = ("competition__id_api", "season")
    list_per_page = 100
    readonly_fields = ("last_run_at", "error_msg")

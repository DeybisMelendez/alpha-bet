from django.contrib import admin

from api_client.models import ApiResponseCache


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
        prefix = "https://api.football-data.org/v4"
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

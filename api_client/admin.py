from django.contrib import admin

from api_client.models import ApiResponseCache


@admin.register(ApiResponseCache)
class ApiResponseCacheAdmin(admin.ModelAdmin):
    list_display = ("url", "fetched_at")
    list_filter = ("fetched_at",)
    search_fields = ("url",)
    readonly_fields = ("fetched_at",)

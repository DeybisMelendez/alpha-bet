from django.db import models


class ApiResponseCache(models.Model):
    url = models.URLField(unique=True)
    body = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["fetched_at"]),
        ]
        verbose_name = "Caché API"
        verbose_name_plural = "Cachés API"

    def __str__(self):
        return f"{self.url[:80]} @ {self.fetched_at:%Y-%m-%d %H:%M}"

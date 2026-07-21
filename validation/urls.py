from django.urls import path

from validation import views

app_name = "validation"

urlpatterns = [
    path("", views.validation_report, name="report"),
    path("evolution/", views.evolution, name="evolution"),
]

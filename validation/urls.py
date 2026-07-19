from django.urls import path

from validation import views

app_name = "validation"

urlpatterns = [
    path("", views.validation_report, name="report"),
]

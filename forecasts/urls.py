from django.urls import path

from . import views

app_name = "forecasts"

urlpatterns = [
    path("", views.forecast_list, name="list"),
    path("calculate/", views.forecast_calculate, name="calculate"),
    path("<int:pk>/", views.forecast_detail, name="detail"),
]
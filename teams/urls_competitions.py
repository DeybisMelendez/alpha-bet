from django.urls import path

from . import views

app_name = "competitions"

urlpatterns = [
    path("", views.competition_list, name="list"),
    path("<str:code>/", views.competition_detail, name="detail"),
    path("<str:code>/<str:season>/", views.competition_detail, name="detail_season"),
]
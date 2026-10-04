from django.urls import path

from . import views


urlpatterns = [
    path(
        "health/",
        views.health,
        name="health",
    ),
    path(
        "settings/openai/",
        views.openai_status,
        name="openai-status",
    ),
    path(
        "settings/openai/save/",
        views.openai_save,
        name="openai-save",
    ),
    path(
        "settings/openai/test/",
        views.openai_test,
        name="openai-test",
    ),
]

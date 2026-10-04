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
    path(
        "missions/create/",
        views.mission_create,
        name="mission-create",
    ),
    path(
        "internal/notify-update/",
        views.notify_update,
        name="notify-update",
    ),
]

# Generated for ARABA research POC.

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ResearchRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        db_index=True,
                        max_length=50,
                    ),
                ),
                (
                    "subject",
                    models.CharField(
                        max_length=240,
                    ),
                ),
                (
                    "location",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=160,
                    ),
                ),
                (
                    "mission",
                    models.JSONField(
                        default=dict,
                    ),
                ),
                (
                    "businesses",
                    models.JSONField(
                        default=list,
                    ),
                ),
                (
                    "recommendation",
                    models.JSONField(
                        default=dict,
                    ),
                ),
                (
                    "basis",
                    models.TextField(
                        blank=True,
                        default="",
                    ),
                ),
                (
                    "is_mock",
                    models.BooleanField(
                        default=True,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]

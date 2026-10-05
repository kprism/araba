from django.db import models


class ResearchRecord(models.Model):
    category = models.CharField(
        max_length=50,
        db_index=True,
    )
    subject = models.CharField(
        max_length=240,
    )
    location = models.CharField(
        max_length=160,
        blank=True,
        default="",
    )
    mission = models.JSONField(
        default=dict,
    )
    businesses = models.JSONField(
        default=list,
    )
    recommendation = models.JSONField(
        default=dict,
    )
    basis = models.TextField(
        blank=True,
        default="",
    )
    is_mock = models.BooleanField(
        default=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        label = self.subject or self.category
        return f"{label} ({self.created_at:%Y-%m-%d %H:%M})"

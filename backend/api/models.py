from django.db import models


class ResearchRecord(models.Model):
    category = models.CharField(max_length=80, db_index=True)
    subject = models.CharField(max_length=240)
    location = models.CharField(max_length=160, blank=True, default="")
    mission = models.JSONField(default=dict)
    businesses = models.JSONField(default=list)
    recommendation = models.JSONField(default=dict)
    basis = models.TextField(blank=True, default="")
    is_mock = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        label = self.subject or self.category
        return f"{label} ({self.created_at:%Y-%m-%d %H:%M})"


class TrainingRule(models.Model):
    category = models.CharField(max_length=80, blank=True, default="", db_index=True)
    trigger = models.CharField(max_length=240)
    instruction = models.TextField()
    example = models.TextField(blank=True, default="")
    source = models.CharField(max_length=30, default="admin")
    signature = models.CharField(max_length=64, unique=True)
    confidence = models.FloatField(default=1.0)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return self.instruction[:80]


class TrainingScenario(models.Model):
    category = models.CharField(max_length=80, blank=True, default="", db_index=True)
    title = models.CharField(max_length=240)
    context = models.JSONField(default=dict)
    goal = models.TextField()
    difficulty = models.CharField(max_length=20, default="보통")
    expected_behaviors = models.JSONField(default=list)
    provider_profile = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="ready", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class TrainingRun(models.Model):
    scenario = models.ForeignKey(
        TrainingScenario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    mode = models.CharField(max_length=30, default="auto")
    transcript = models.JSONField(default=list)
    score = models.PositiveSmallIntegerField(default=0)
    mistakes = models.JSONField(default=list)
    learned_rules = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.mode} {self.score}"

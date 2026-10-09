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


class Business(models.Model):
    provider = models.CharField(max_length=30, default="kakao", db_index=True)
    provider_place_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    identity_key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=240, db_index=True)
    normalized_name = models.CharField(max_length=240, blank=True, default="", db_index=True)
    category = models.CharField(max_length=320, blank=True, default="", db_index=True)
    address = models.CharField(max_length=320, blank=True, default="", db_index=True)
    road_address = models.CharField(max_length=320, blank=True, default="")
    lot_address = models.CharField(max_length=320, blank=True, default="")
    phone = models.CharField(max_length=80, blank=True, default="")
    latitude = models.CharField(max_length=40, blank=True, default="")
    longitude = models.CharField(max_length=40, blank=True, default="")
    place_url = models.URLField(max_length=500, blank=True, default="")
    snapshot = models.JSONField(default=dict)
    source_meta = models.JSONField(default=dict)
    active = models.BooleanField(default=True, db_index=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True, db_index=True)
    last_external_refresh_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_detail_refresh_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-last_seen_at",)
        indexes = [
            models.Index(fields=("provider", "provider_place_id")),
            models.Index(fields=("category", "address")),
        ]

    def __str__(self):
        return self.name


class BusinessFact(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="facts",
    )
    key = models.CharField(max_length=80, db_index=True)
    value = models.JSONField(default=dict)
    source = models.CharField(max_length=40, default="araba", db_index=True)
    confidence = models.FloatField(default=1.0)
    observed_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("business", "key", "source"),
                name="uniq_business_fact_source",
            ),
        ]

    def __str__(self):
        return f"{self.business.name}:{self.key}"


class BusinessExperience(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="experiences",
    )
    raw_text = models.TextField()
    structured = models.JSONField(default=dict)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    verified_visit = models.BooleanField(default=False, db_index=True)
    source = models.CharField(max_length=30, default="user")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.business.name} experience #{self.pk}"


class BusinessRealtimeSignal(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="realtime_signals",
    )
    key = models.CharField(max_length=80, db_index=True)
    value = models.JSONField(default=dict)
    source = models.CharField(max_length=40, default="business_ai")
    observed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ("-observed_at",)

    def __str__(self):
        return f"{self.business.name}:{self.key}"

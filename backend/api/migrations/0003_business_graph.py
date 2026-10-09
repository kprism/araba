from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0002_training_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="Business",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(db_index=True, default="kakao", max_length=30)),
                ("provider_place_id", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("identity_key", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(db_index=True, max_length=240)),
                ("normalized_name", models.CharField(blank=True, db_index=True, default="", max_length=240)),
                ("category", models.CharField(blank=True, db_index=True, default="", max_length=320)),
                ("address", models.CharField(blank=True, db_index=True, default="", max_length=320)),
                ("road_address", models.CharField(blank=True, default="", max_length=320)),
                ("lot_address", models.CharField(blank=True, default="", max_length=320)),
                ("phone", models.CharField(blank=True, default="", max_length=80)),
                ("latitude", models.CharField(blank=True, default="", max_length=40)),
                ("longitude", models.CharField(blank=True, default="", max_length=40)),
                ("place_url", models.URLField(blank=True, default="", max_length=500)),
                ("snapshot", models.JSONField(default=dict)),
                ("source_meta", models.JSONField(default=dict)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("last_external_refresh_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_detail_refresh_at", models.DateTimeField(blank=True, db_index=True, null=True)),
            ],
            options={"ordering": ("-last_seen_at",)},
        ),
        migrations.CreateModel(
            name="BusinessFact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(db_index=True, max_length=80)),
                ("value", models.JSONField(default=dict)),
                ("source", models.CharField(db_index=True, default="araba", max_length=40)),
                ("confidence", models.FloatField(default=1.0)),
                ("observed_at", models.DateTimeField(auto_now=True)),
                ("expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="facts", to="api.business")),
            ],
        ),
        migrations.CreateModel(
            name="BusinessExperience",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("raw_text", models.TextField()),
                ("structured", models.JSONField(default=dict)),
                ("rating", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("verified_visit", models.BooleanField(db_index=True, default=False)),
                ("source", models.CharField(default="user", max_length=30)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="experiences", to="api.business")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="BusinessRealtimeSignal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(db_index=True, max_length=80)),
                ("value", models.JSONField(default=dict)),
                ("source", models.CharField(default="business_ai", max_length=40)),
                ("observed_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="realtime_signals", to="api.business")),
            ],
            options={"ordering": ("-observed_at",)},
        ),
        migrations.AddIndex(
            model_name="business",
            index=models.Index(fields=["provider", "provider_place_id"], name="api_busines_provide_6ddf22_idx"),
        ),
        migrations.AddIndex(
            model_name="business",
            index=models.Index(fields=["category", "address"], name="api_busines_categor_2c46a3_idx"),
        ),
        migrations.AddConstraint(
            model_name="businessfact",
            constraint=models.UniqueConstraint(fields=("business", "key", "source"), name="uniq_business_fact_source"),
        ),
    ]

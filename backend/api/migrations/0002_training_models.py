from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0001_researchrecord"),
    ]

    operations = [
        migrations.AlterField(
            model_name="researchrecord",
            name="category",
            field=models.CharField(db_index=True, max_length=80),
        ),
        migrations.CreateModel(
            name="TrainingRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(blank=True, db_index=True, default="", max_length=80)),
                ("trigger", models.CharField(max_length=240)),
                ("instruction", models.TextField()),
                ("example", models.TextField(blank=True, default="")),
                ("source", models.CharField(default="admin", max_length=30)),
                ("signature", models.CharField(max_length=64, unique=True)),
                ("confidence", models.FloatField(default=1.0)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-updated_at",)},
        ),
        migrations.CreateModel(
            name="TrainingScenario",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(blank=True, db_index=True, default="", max_length=80)),
                ("title", models.CharField(max_length=240)),
                ("context", models.JSONField(default=dict)),
                ("goal", models.TextField()),
                ("difficulty", models.CharField(default="보통", max_length=20)),
                ("expected_behaviors", models.JSONField(default=list)),
                ("provider_profile", models.JSONField(default=dict)),
                ("status", models.CharField(db_index=True, default="ready", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="TrainingRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(default="auto", max_length=30)),
                ("transcript", models.JSONField(default=list)),
                ("score", models.PositiveSmallIntegerField(default=0)),
                ("mistakes", models.JSONField(default=list)),
                ("learned_rules", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("scenario", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="runs", to="api.trainingscenario")),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]

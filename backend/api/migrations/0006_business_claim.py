from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_clear_unverified_business_images"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessClaim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(max_length=12, default="pending", choices=[("pending", "심사중"), ("approved", "인증완료"), ("rejected", "거절")], db_index=True)),
                ("owner_name", models.CharField(max_length=100)),
                ("registration_hash", models.CharField(max_length=64)),
                ("registration_last4", models.CharField(max_length=4)),
                ("contact_phone", models.CharField(max_length=30, blank=True, default="")),
                ("proposed_info", models.JSONField(default=dict)),
                ("extra_information", models.TextField(blank=True, default="")),
                ("agent_instructions", models.TextField(blank=True, default="")),
                ("review_note", models.TextField(blank=True, default="")),
                ("reviewed_at", models.DateTimeField(null=True, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(to="api.business", related_name="ownership_claims", on_delete=django.db.models.deletion.CASCADE)),
                ("user", models.ForeignKey(to=settings.AUTH_USER_MODEL, related_name="araba_business_claims", on_delete=django.db.models.deletion.CASCADE)),
                ("reviewed_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, related_name="reviewed_araba_business_claims", null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="businessclaim",
            constraint=models.UniqueConstraint(fields=("user", "business"), name="uniq_business_claim_per_user"),
        ),
        migrations.AddConstraint(
            model_name="businessclaim",
            constraint=models.UniqueConstraint(fields=("business",), condition=models.Q(status="approved"), name="uniq_approved_business_owner"),
        ),
    ]

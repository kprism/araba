from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0003_business_graph"),
    ]

    operations = [
        migrations.CreateModel(
            name="LabCase",
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
                    "actor_role",
                    models.CharField(
                        db_index=True,
                        default="trainer",
                        max_length=20,
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        max_length=80,
                    ),
                ),
                (
                    "input_source",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=20,
                    ),
                ),
                ("report_text", models.TextField()),
                (
                    "request_text",
                    models.TextField(
                        blank=True,
                        default="",
                    ),
                ),
                (
                    "assistant_response",
                    models.TextField(
                        blank=True,
                        default="",
                    ),
                ),
                (
                    "root_cause_type",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        max_length=40,
                    ),
                ),
                (
                    "diagnosis",
                    models.JSONField(default=dict),
                ),
                (
                    "repair_plan",
                    models.JSONField(default=dict),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            (
                                "user_feedback_candidate",
                                "사용자 학습 후보",
                            ),
                            ("diagnosed", "진단 완료"),
                            (
                                "rule_applied",
                                "학습 규칙 반영",
                            ),
                            (
                                "code_fix_required",
                                "코드 보완 필요",
                            ),
                            (
                                "ready_for_retest",
                                "재시험 대기",
                            ),
                            ("closed", "완료"),
                        ],
                        db_index=True,
                        default="diagnosed",
                        max_length=40,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "training_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lab_cases",
                        to="api.trainingrun",
                    ),
                ),
            ],
            options={
                "ordering": ("-updated_at",),
            },
        ),
    ]

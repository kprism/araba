from django.db import migrations


TRUSTED_IMAGE_SOURCES = {
    "kakao_place",
    "naver_place",
    "google_places",
    "business_official",
}


def clear_unverified_business_images(apps, schema_editor):
    Business = apps.get_model("api", "Business")
    BusinessFact = apps.get_model("api", "BusinessFact")

    BusinessFact.objects.filter(
        key="image_url",
    ).exclude(
        source__in=TRUSTED_IMAGE_SOURCES,
    ).delete()

    for record in Business.objects.all().iterator():
        snapshot = record.snapshot
        if not isinstance(snapshot, dict):
            continue

        image_url = str(
            snapshot.get("image_url") or ""
        ).strip()
        if not image_url:
            continue

        image_source = str(
            snapshot.get("image_source") or ""
        ).strip()
        if image_source in TRUSTED_IMAGE_SOURCES:
            continue

        cleaned = dict(snapshot)
        for key in (
            "image_url",
            "image_source",
            "image_source_url",
            "image_caption",
        ):
            cleaned.pop(key, None)

        record.snapshot = cleaned
        record.save(
            update_fields=["snapshot"]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0004_labcase"),
    ]

    operations = [
        migrations.RunPython(
            clear_unverified_business_images,
            migrations.RunPython.noop,
        ),
    ]

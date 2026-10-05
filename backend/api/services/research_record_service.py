from collections import OrderedDict

from api.models import ResearchRecord


def save_research_record(mission, result):
    category = str(
        mission.get("category") or "기타"
    ).strip() or "기타"
    subject = str(
        mission.get("subject") or ""
    ).strip()
    location = str(
        mission.get("location") or ""
    ).strip()

    businesses = result.get("businesses")
    if not isinstance(businesses, list):
        businesses = []

    recommendation = result.get("recommendation")
    if not isinstance(recommendation, dict):
        recommendation = {}

    record = ResearchRecord.objects.create(
        category=category,
        subject=subject,
        location=location,
        mission=mission,
        businesses=businesses,
        recommendation=recommendation,
        basis=str(result.get("basis") or "").strip(),
        is_mock=bool(result.get("mock", False)),
    )

    return record


def _serialize_record(record):
    recommendation = (
        record.recommendation
        if isinstance(record.recommendation, dict)
        else {}
    )

    return {
        "id": record.id,
        "category": record.category,
        "subject": record.subject,
        "location": record.location,
        "is_mock": record.is_mock,
        "created_at": record.created_at.isoformat(),
        "business_count": (
            len(record.businesses)
            if isinstance(record.businesses, list)
            else 0
        ),
        "recommendation": recommendation,
        "basis": record.basis,
    }


def list_research_records_grouped(limit=50):
    limit = max(1, min(100, int(limit)))
    records = list(
        ResearchRecord.objects.all()[:limit]
    )

    grouped = OrderedDict()

    for record in records:
        grouped.setdefault(
            record.category,
            [],
        ).append(
            _serialize_record(record)
        )

    categories = [
        {
            "category": category,
            "count": len(items),
            "records": items,
        }
        for category, items in grouped.items()
    ]

    return {
        "total_count": len(records),
        "categories": categories,
    }

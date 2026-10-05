from collections import Counter, OrderedDict

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


def _string_list(value):
    if not isinstance(value, list):
        return []

    return [
        str(item).strip()
        for item in value
        if str(item).strip()
    ]


def _attributes(value):
    if not isinstance(value, dict):
        return {}

    normalized = {}

    for key, raw in value.items():
        name = str(key).strip()
        if not name:
            continue

        if isinstance(raw, list):
            values = [
                str(item).strip()
                for item in raw
                if str(item).strip()
            ]
            if values:
                normalized[name] = values
            continue

        if raw is None:
            continue

        text = str(raw).strip()
        if text:
            normalized[name] = text

    return normalized


def _serialize_record(record):
    recommendation = (
        record.recommendation
        if isinstance(record.recommendation, dict)
        else {}
    )
    mission = (
        record.mission
        if isinstance(record.mission, dict)
        else {}
    )

    return {
        "id": record.id,
        "category": record.category,
        "subcategories": _string_list(
            mission.get("subcategories")
        ),
        "intent": str(
            mission.get("intent") or ""
        ).strip(),
        "attributes": _attributes(
            mission.get("attributes")
        ),
        "comparison": str(
            mission.get("comparison") or ""
        ).strip(),
        "subject": record.subject,
        "location": record.location,
        "is_mock": record.is_mock,
        "created_at": record.created_at.isoformat(),
        "business_count": (
            len(record.businesses)
            if isinstance(record.businesses, list)
            else 0
        ),
        "businesses": (
            record.businesses
            if isinstance(record.businesses, list)
            else []
        ),
        "recommendation": recommendation,
        "basis": record.basis,
    }


def _option_list(counter):
    return [
        {
            "value": value,
            "count": count,
        }
        for value, count in counter.most_common()
        if value
    ]


def _filters_for_category(records):
    subcategories = Counter()
    locations = Counter()
    intents = Counter()
    comparisons = Counter()
    dynamic_attributes = {}

    for item in records:
        subcategories.update(
            item.get("subcategories") or []
        )

        location = item.get("location")
        if location:
            locations.update([location])

        intent = item.get("intent")
        if intent:
            intents.update([intent])

        comparison = item.get("comparison")
        if comparison:
            comparisons.update([comparison])

        for key, raw in (
            item.get("attributes") or {}
        ).items():
            counter = dynamic_attributes.setdefault(
                key,
                Counter(),
            )

            if isinstance(raw, list):
                counter.update(raw)
            else:
                counter.update([str(raw)])

    sections = []

    def add_section(key, label, counter):
        options = _option_list(counter)
        if not options:
            return

        sections.append(
            {
                "key": key,
                "label": label,
                "options": options,
            }
        )

    add_section(
        "subcategory",
        "세부 분류",
        subcategories,
    )
    add_section(
        "location",
        "지역",
        locations,
    )
    add_section(
        "intent",
        "목적",
        intents,
    )
    add_section(
        "comparison",
        "선택 기준",
        comparisons,
    )

    for key in sorted(dynamic_attributes):
        add_section(
            f"attribute:{key}",
            key,
            dynamic_attributes[key],
        )

    return {
        "count": len(records),
        "sections": sections,
    }


def list_research_records_grouped(limit=100):
    limit = max(1, min(200, int(limit)))
    records = list(
        ResearchRecord.objects.all()[:limit]
    )
    serialized = [
        _serialize_record(record)
        for record in records
    ]

    grouped = OrderedDict()

    for item in serialized:
        grouped.setdefault(
            item["category"],
            [],
        ).append(item)

    categories = [
        {
            "category": category,
            "count": len(items),
            "records": items,
        }
        for category, items in grouped.items()
    ]

    category_counts = Counter(
        item["category"]
        for item in serialized
        if item.get("category")
    )

    return {
        "total_count": len(serialized),
        "categories": categories,
        "filters": {
            "categories": _option_list(
                category_counts
            ),
            "by_category": {
                category: _filters_for_category(
                    items
                )
                for category, items in grouped.items()
            },
        },
    }

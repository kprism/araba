import re
from collections import Counter
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from api.models import Business, BusinessExperience, BusinessFact


DETAIL_FRESH_HOURS = 24
ALLOWED_SORTS = {
    "latest": "-last_seen_at",
    "oldest": "last_seen_at",
    "name": "name",
}


def _category_label(value):
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "미분류"

    parts = [
        item.strip()
        for item in re.split(r"\s*>\s*|\s*,\s*", text)
        if item.strip()
    ]
    return parts[-1] if parts else text


def _truthy(value):
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _annotated_queryset():
    facts = BusinessFact.objects.filter(
        business_id=OuterRef("pk"),
    )
    experiences = BusinessExperience.objects.filter(
        business_id=OuterRef("pk"),
    )

    return Business.objects.annotate(
        has_hours=Exists(
            facts.filter(key="opening_hours")
        ),
        has_parking=Exists(
            facts.filter(key="parking_available")
        ),
        has_prices=Exists(
            facts.filter(key="prices")
        ),
        has_image=Exists(
            facts.filter(key="image_url")
        ),
        has_experience=Exists(experiences),
        experience_count=Count(
            "experiences",
            distinct=True,
        ),
    )


def _global_summary():
    now = timezone.now()
    fresh_cutoff = now - timedelta(
        hours=DETAIL_FRESH_HOURS
    )
    all_qs = _annotated_queryset()
    active_qs = all_qs.filter(active=True)

    categories = Counter(
        _category_label(value)
        for value in active_qs.values_list(
            "category",
            flat=True,
        )
    )
    category_counts = [
        {
            "category": category,
            "count": count,
        }
        for category, count in sorted(
            categories.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    ]

    provider_counts = list(
        active_qs.values("provider")
        .annotate(count=Count("id"))
        .order_by("-count", "provider")
    )

    active_count = active_qs.count()
    fresh_detail_count = active_qs.filter(
        last_detail_refresh_at__gte=fresh_cutoff,
    ).count()

    return {
        "total_count": all_qs.count(),
        "active_count": active_count,
        "inactive_count": all_qs.filter(
            active=False
        ).count(),
        "fresh_detail_count": fresh_detail_count,
        "stale_detail_count": max(
            0,
            active_count - fresh_detail_count,
        ),
        "category_counts": category_counts,
        "provider_counts": provider_counts,
        "coverage": {
            "phone": active_qs.exclude(
                phone=""
            ).count(),
            "hours": active_qs.filter(
                has_hours=True
            ).count(),
            "parking": active_qs.filter(
                has_parking=True
            ).count(),
            "prices": active_qs.filter(
                has_prices=True
            ).count(),
            "image": active_qs.filter(
                has_image=True
            ).count(),
            "experience": active_qs.filter(
                has_experience=True
            ).count(),
        },
    }


def _apply_filters(queryset, params):
    search = str(
        params.get("q", "")
    ).strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(category__icontains=search)
            | Q(address__icontains=search)
            | Q(road_address__icontains=search)
            | Q(lot_address__icontains=search)
            | Q(phone__icontains=search)
        )

    category = str(
        params.get("category", "")
    ).strip()
    if category and category != "전체":
        if category == "미분류":
            queryset = queryset.filter(
                category=""
            )
        else:
            queryset = queryset.filter(
                category__icontains=category
            )

    provider = str(
        params.get("provider", "")
    ).strip()
    if provider and provider != "전체":
        queryset = queryset.filter(
            provider=provider
        )

    active = str(
        params.get("active", "active")
    ).strip().lower()
    if active == "active":
        queryset = queryset.filter(active=True)
    elif active == "inactive":
        queryset = queryset.filter(active=False)

    freshness = str(
        params.get("freshness", "all")
    ).strip().lower()
    cutoff = timezone.now() - timedelta(
        hours=DETAIL_FRESH_HOURS
    )
    if freshness == "fresh":
        queryset = queryset.filter(
            last_detail_refresh_at__gte=cutoff
        )
    elif freshness == "stale":
        queryset = queryset.filter(
            Q(last_detail_refresh_at__lt=cutoff)
            | Q(last_detail_refresh_at__isnull=True)
        )

    if _truthy(params.get("has_phone")):
        queryset = queryset.exclude(phone="")
    if _truthy(params.get("has_hours")):
        queryset = queryset.filter(has_hours=True)
    if _truthy(params.get("has_parking")):
        queryset = queryset.filter(
            has_parking=True
        )
    if _truthy(params.get("has_prices")):
        queryset = queryset.filter(has_prices=True)
    if _truthy(params.get("has_image")):
        queryset = queryset.filter(has_image=True)
    if _truthy(params.get("has_experience")):
        queryset = queryset.filter(
            has_experience=True
        )

    return queryset


def _serialize(record):
    cutoff = timezone.now() - timedelta(
        hours=DETAIL_FRESH_HOURS
    )
    snapshot = (
        record.snapshot
        if isinstance(record.snapshot, dict)
        else {}
    )
    return {
        "id": record.id,
        "provider": record.provider,
        "provider_place_id": record.provider_place_id,
        "name": record.name,
        "category": record.category,
        "category_label": _category_label(
            record.category
        ),
        "address": (
            record.road_address
            or record.address
            or record.lot_address
        ),
        "phone": record.phone,
        "place_url": record.place_url,
        "active": record.active,
        "last_seen_at": (
            record.last_seen_at.isoformat()
            if record.last_seen_at
            else None
        ),
        "last_detail_refresh_at": (
            record.last_detail_refresh_at.isoformat()
            if record.last_detail_refresh_at
            else None
        ),
        "detail_fresh": bool(
            record.last_detail_refresh_at
            and record.last_detail_refresh_at
            >= cutoff
        ),
        "has_phone": bool(record.phone),
        "has_hours": bool(record.has_hours),
        "has_parking": bool(record.has_parking),
        "has_prices": bool(record.has_prices),
        "has_image": bool(record.has_image),
        "has_experience": bool(
            record.has_experience
        ),
        "experience_count": int(
            record.experience_count or 0
        ),
        "image_url": str(
            snapshot.get("image_url") or ""
        ).strip(),
    }


def business_admin_dashboard(params):
    queryset = _annotated_queryset()
    queryset = _apply_filters(
        queryset,
        params,
    )

    try:
        page = max(
            1,
            int(params.get("page", 1)),
        )
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = max(
            10,
            min(
                100,
                int(params.get("page_size", 30)),
            ),
        )
    except (TypeError, ValueError):
        page_size = 30

    sort_key = str(
        params.get("sort", "latest")
    ).strip()
    ordering = ALLOWED_SORTS.get(
        sort_key,
        ALLOWED_SORTS["latest"],
    )

    filtered_count = queryset.count()
    offset = (page - 1) * page_size
    records = list(
        queryset.order_by(
            ordering,
            "id",
        )[offset : offset + page_size]
    )

    return {
        "summary": _global_summary(),
        "filtered_count": filtered_count,
        "page": page,
        "page_size": page_size,
        "has_more": (
            offset + len(records)
            < filtered_count
        ),
        "businesses": [
            _serialize(record)
            for record in records
        ],
    }

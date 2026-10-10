import hashlib
import re
from copy import deepcopy
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from api.models import Business, BusinessExperience, BusinessFact


DETAIL_CACHE_TTL_HOURS = 24

STRICT_FOOD_TERMS = {
    "피자",
    "치킨",
    "햄버거",
    "버거",
    "초밥",
    "스시",
    "파스타",
    "족발",
    "보쌈",
    "곱창",
    "막창",
    "떡볶이",
    "샌드위치",
    "베이커리",
    "빵",
}

INCOMPATIBLE_FOOD_VENUE_MARKERS = (
    "술집",
    "주점",
    "호프",
    "맥주",
    "와인바",
    "칵테일바",
    "bar",
)

FACT_TTLS = {
    "opening_hours": timedelta(days=2),
    "parking_available": timedelta(days=30),
    "prices": timedelta(days=7),
    "image_url": timedelta(days=30),
    "phone": timedelta(days=90),
    "address": timedelta(days=180),
}


def _clean(value):
    return " ".join(str(value or "").split()).strip()


def _normalized(value):
    return re.sub(
        r"[^0-9a-zA-Z가-힣]+",
        "",
        _clean(value),
    ).lower()


def _identity_key(business):
    provider = _clean(business.get("source") or "kakao")
    provider_place_id = _clean(business.get("id"))
    if provider_place_id:
        raw = f"{provider}:{provider_place_id}"
    else:
        raw = "|".join(
            [
                _normalized(business.get("name")),
                _normalized(
                    business.get("road_address")
                    or business.get("address")
                ),
                _normalized(business.get("phone")),
            ]
        )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _meaningful(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _deep_merge(base, incoming):
    result = deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(incoming, dict):
        return result

    for key, value in incoming.items():
        if isinstance(value, dict):
            current = result.get(key)
            result[key] = _deep_merge(
                current if isinstance(current, dict) else {},
                value,
            )
        elif _meaningful(value):
            result[key] = deepcopy(value)
    return result


def _fact_payloads(business):
    payloads = {
        "address": business.get("address"),
        "phone": business.get("phone"),
        "image_url": business.get("image_url"),
    }

    naver = business.get("naver")
    if isinstance(naver, dict):
        payloads.update(
            {
                "opening_hours": naver.get("opening_hours"),
                "parking_available": naver.get("parking_available"),
                "prices": naver.get("prices"),
            }
        )

    return {
        key: value
        for key, value in payloads.items()
        if _meaningful(value)
    }


def _fact_source(business, key):
    if key in {"opening_hours", "parking_available", "prices"}:
        naver = business.get("naver")
        if isinstance(naver, dict) and naver.get("matched") is True:
            return "naver_place"
        if isinstance(business.get("openai_web"), dict):
            return "openai_web"
    if key == "image_url":
        return _clean(business.get("image_source")) or "web"
    return _clean(business.get("source")) or "kakao"


def _save_facts(record, business):
    now = timezone.now()
    for key, value in _fact_payloads(business).items():
        ttl = FACT_TTLS.get(key)
        BusinessFact.objects.update_or_create(
            business=record,
            key=key,
            source=_fact_source(business, key),
            defaults={
                "value": {"value": value},
                "confidence": 1.0,
                "expires_at": now + ttl if ttl else None,
            },
        )


def _experience_summary(record):
    experiences = list(
        record.experiences.all()[:5]
    )
    return {
        "experience_count": record.experiences.count(),
        "verified_experience_count": record.experiences.filter(
            verified_visit=True
        ).count(),
        "experience_snippets": [
            item.raw_text[:120]
            for item in experiences[:3]
        ],
        "experience_signals": [
            item.structured
            for item in experiences[:3]
            if isinstance(item.structured, dict)
            and item.structured
        ],
    }


def serialize_business(record, *, cache_hit=True):
    snapshot = (
        deepcopy(record.snapshot)
        if isinstance(record.snapshot, dict)
        else {}
    )
    snapshot.update(
        {
            "id": record.provider_place_id or snapshot.get("id", ""),
            "name": record.name,
            "category": record.category,
            "address": record.address,
            "road_address": record.road_address,
            "lot_address": record.lot_address,
            "phone": record.phone,
            "latitude": record.latitude,
            "longitude": record.longitude,
            "place_url": record.place_url,
            "source": snapshot.get("source") or record.provider,
        }
    )

    now = timezone.now()
    detail_fresh = bool(
        record.last_detail_refresh_at
        and record.last_detail_refresh_at
        >= now - timedelta(hours=DETAIL_CACHE_TTL_HOURS)
    )
    fresh_fact_keys = list(
        record.facts.filter(
            Q(expires_at__isnull=True)
            | Q(expires_at__gt=now)
        ).values_list("key", flat=True)
    )

    snapshot.update(
        {
            "araba_business_id": record.id,
            "araba_cache_hit": cache_hit,
            "araba_data_source": "araba_db" if cache_hit else "external",
            "araba_last_seen_at": record.last_seen_at.isoformat(),
            "araba_last_detail_refresh_at": (
                record.last_detail_refresh_at.isoformat()
                if record.last_detail_refresh_at
                else None
            ),
            "araba_detail_fresh": detail_fresh,
            "araba_fresh_facts": fresh_fact_keys,
            **_experience_summary(record),
        }
    )
    return snapshot


def _upsert_business(business, mission=None, *, detail_refreshed=False):
    identity_key = _identity_key(business)
    now = timezone.now()
    provider = _clean(business.get("source") or "kakao")[:30] or "kakao"
    provider_place_id = _clean(business.get("id"))[:120]
    name = _clean(business.get("name"))[:240]
    if not name:
        return None

    record, created = Business.objects.get_or_create(
        identity_key=identity_key,
        defaults={
            "provider": provider,
            "provider_place_id": provider_place_id,
            "name": name,
            "normalized_name": _normalized(name)[:240],
        },
    )

    snapshot = _deep_merge(
        record.snapshot if isinstance(record.snapshot, dict) else {},
        business,
    )
    source_meta = (
        deepcopy(record.source_meta)
        if isinstance(record.source_meta, dict)
        else {}
    )
    source_meta[provider] = {
        "last_seen_at": now.isoformat(),
        "mission_category": _clean((mission or {}).get("category")),
        "mission_location": _clean((mission or {}).get("location")),
    }

    record.provider = provider
    record.provider_place_id = provider_place_id or record.provider_place_id
    record.name = name
    record.normalized_name = _normalized(name)[:240]
    record.category = _clean(
        business.get("category") or record.category
    )[:320]
    record.address = _clean(
        business.get("address") or record.address
    )[:320]
    record.road_address = _clean(
        business.get("road_address") or record.road_address
    )[:320]
    record.lot_address = _clean(
        business.get("lot_address") or record.lot_address
    )[:320]
    record.phone = _clean(
        business.get("phone") or record.phone
    )[:80]
    record.latitude = _clean(
        business.get("latitude") or record.latitude
    )[:40]
    record.longitude = _clean(
        business.get("longitude") or record.longitude
    )[:40]
    record.place_url = _clean(
        business.get("place_url") or record.place_url
    )[:500]
    record.snapshot = snapshot
    record.source_meta = source_meta
    record.last_external_refresh_at = now
    if detail_refreshed:
        record.last_detail_refresh_at = now

    fields = [
        "provider",
        "provider_place_id",
        "name",
        "normalized_name",
        "category",
        "address",
        "road_address",
        "lot_address",
        "phone",
        "latitude",
        "longitude",
        "place_url",
        "snapshot",
        "source_meta",
        "last_external_refresh_at",
        "last_seen_at",
    ]
    if detail_refreshed:
        fields.append("last_detail_refresh_at")
    if created:
        record.save()
    else:
        record.save(update_fields=fields)

    _save_facts(record, business)
    return record


def persist_businesses(
    businesses,
    mission=None,
    *,
    detail_refreshed=False,
):
    result = []
    for item in businesses or []:
        if not isinstance(item, dict):
            continue
        existed = _record_for_candidate(item) is not None
        record = _upsert_business(
            item,
            mission,
            detail_refreshed=detail_refreshed,
        )
        if record is not None:
            serialized = serialize_business(
                record,
                cache_hit=existed,
            )
            if existed:
                serialized["araba_data_source"] = (
                    "araba_db+external_refresh"
                )
            result.append(serialized)
    return result


def _record_for_candidate(business):
    identity_key = _identity_key(business)
    return Business.objects.filter(
        identity_key=identity_key,
        active=True,
    ).first()


def merge_businesses_from_graph(businesses):
    merged = []
    for item in businesses or []:
        if not isinstance(item, dict):
            continue
        record = _record_for_candidate(item)
        if record is None:
            merged.append(dict(item))
            continue

        cached = serialize_business(record, cache_hit=True)
        combined = _deep_merge(cached, item)
        combined.update(
            {
                "araba_business_id": record.id,
                "araba_cache_hit": True,
                "araba_data_source": "araba_db+external_identity",
                "araba_detail_fresh": cached.get(
                    "araba_detail_fresh", False
                ),
                "experience_count": cached.get(
                    "experience_count", 0
                ),
                "verified_experience_count": cached.get(
                    "verified_experience_count", 0
                ),
                "experience_snippets": cached.get(
                    "experience_snippets", []
                ),
                "experience_signals": cached.get(
                    "experience_signals", []
                ),
            }
        )
        merged.append(combined)
    return merged


def _mission_terms(mission):
    values = []
    target = _clean(mission.get("target_business"))
    if target:
        values.append(target)

    raw_terms = mission.get("search_terms")
    if isinstance(raw_terms, list):
        values.extend(_clean(item) for item in raw_terms)

    raw_subcategories = mission.get("subcategories")
    if isinstance(raw_subcategories, list):
        values.extend(_clean(item) for item in raw_subcategories)

    subject = _clean(
        mission.get("subject")
    )
    subject_is_strict_food = any(
        term in subject
        for term in STRICT_FOOD_TERMS
    )
    if (
        subject_is_strict_food
        and subject
        and subject not in values
    ):
        values.append(subject)

    if not values:
        values.append(
            subject
            or _clean(mission.get("category"))
        )

    generic = {
        "기타",
        "예약",
        "의료",
        "식당",
        "음식점",
        "가게",
        "업체",
        "장소",
    }
    tokens = []
    for value in values:
        for token in re.findall(
            r"[0-9a-zA-Z가-힣]{2,}",
            value,
        ):
            if token not in generic and token not in tokens:
                tokens.append(token)
    return tokens[:6]


def _location_tokens(location):
    tokens = re.findall(
        r"[0-9a-zA-Z가-힣]{2,}",
        _clean(location),
    )
    return tokens[-3:]


def cached_businesses_for_mission(mission, requested_count=5):
    if not isinstance(mission, dict):
        return {"businesses": [], "complete": False}

    target = _clean(mission.get("target_business"))
    location = _clean(mission.get("location"))
    terms = _mission_terms(mission)
    location_tokens = _location_tokens(location)

    queryset = Business.objects.filter(active=True)

    if target:
        queryset = queryset.filter(
            Q(name__icontains=target)
            | Q(normalized_name__icontains=_normalized(target))
        )

    candidates = list(queryset.order_by("-last_seen_at")[:200])
    ranked = []

    for record in candidates:
        location_haystack = " ".join(
            [
                record.address,
                record.road_address,
                record.lot_address,
            ]
        )
        if location_tokens and not all(
            token in location_haystack
            for token in location_tokens
        ):
            continue

        haystack = " ".join(
            [
                record.name,
                record.category,
                record.address,
                _clean(record.snapshot.get("description"))
                if isinstance(record.snapshot, dict)
                else "",
            ]
        ).lower()

        category_text = _clean(
            record.category
        ).lower()
        strict_food = [
            token
            for token in terms
            if token in STRICT_FOOD_TERMS
        ]

        if strict_food and any(
            marker in category_text
            for marker in INCOMPATIBLE_FOOD_VENUE_MARKERS
        ):
            continue

        if strict_food and not any(
            token.lower() in haystack
            for token in strict_food
        ):
            continue

        if terms and not any(
            token.lower() in haystack
            for token in terms
        ):
            continue

        score = 0
        if target and target.lower() in record.name.lower():
            score += 10
        score += sum(
            2 for token in location_tokens
            if token in location_haystack
        )
        score += sum(
            3 for token in terms
            if token.lower() in haystack
        )
        ranked.append((score, record.last_seen_at, record))

    ranked.sort(
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    limit = max(1, min(int(requested_count or 5), 10))
    selected = [
        serialize_business(item[2], cache_hit=True)
        for item in ranked[:limit]
    ]

    complete = bool(selected) if target else len(selected) >= limit
    return {
        "businesses": selected,
        "complete": complete,
    }


def _structure_experience(text):
    normalized = _clean(text)
    signals = {}
    tags = []

    wait_match = re.search(
        r"(?:대기|기다(?:렸|린|림|리))[^0-9]{0,8}(\d{1,3})\s*분",
        normalized,
    )
    if wait_match is None:
        wait_match = re.search(
            r"(\d{1,3})\s*분[^가-힣]{0,4}(?:대기|기다)",
            normalized,
        )
    if wait_match:
        signals["wait_minutes"] = int(wait_match.group(1))
        tags.append(f"대기 {wait_match.group(1)}분")

    if re.search(r"주차.{0,8}(불편|좁|힘들|어렵|복잡)", normalized):
        signals["parking_experience"] = "difficult"
        tags.append("주차 불편")
    elif re.search(r"주차.{0,8}(편하|넓|쉬|좋)", normalized):
        signals["parking_experience"] = "easy"
        tags.append("주차 편리")

    if re.search(r"(설명|안내).{0,8}(자세|친절|좋)", normalized):
        signals["explanation"] = "positive"
        tags.append("설명 만족")
    if re.search(r"(친절|상냥|응대.{0,5}좋)", normalized):
        signals["service"] = "positive"
        tags.append("친절")
    if re.search(r"(비싸|가격.{0,5}높|비용.{0,5}높)", normalized):
        signals["price_feeling"] = "expensive"
        tags.append("가격 높음")
    elif re.search(r"(저렴|싸다|가격.{0,5}괜찮)", normalized):
        signals["price_feeling"] = "reasonable"
        tags.append("가격 만족")

    return {
        "signals": signals,
        "tags": tags,
        "parser": "araba-experience-v1",
    }


def add_business_experience(
    *,
    business_id=None,
    provider_place_id=None,
    raw_text,
    rating=None,
    verified_visit=False,
):
    text = _clean(raw_text)
    if len(text) < 2:
        raise ValueError("이용 경험을 조금 더 자세히 적어주세요.")

    record = None
    if business_id:
        record = Business.objects.filter(
            pk=business_id,
            active=True,
        ).first()
    if record is None and provider_place_id:
        record = Business.objects.filter(
            provider_place_id=_clean(provider_place_id),
            active=True,
        ).first()
    if record is None:
        raise ValueError("후기를 연결할 ARABA 상점 정보를 찾지 못했습니다.")

    parsed_rating = None
    if rating not in (None, ""):
        try:
            parsed_rating = int(rating)
        except (TypeError, ValueError) as exc:
            raise ValueError("평점은 1~5 사이 숫자여야 합니다.") from exc
        if not 1 <= parsed_rating <= 5:
            raise ValueError("평점은 1~5 사이여야 합니다.")

    experience = BusinessExperience.objects.create(
        business=record,
        raw_text=text,
        structured=_structure_experience(text),
        rating=parsed_rating,
        verified_visit=bool(verified_visit),
        source="user",
    )
    summary = _experience_summary(record)
    return {
        "id": experience.id,
        "business_id": record.id,
        "business_name": record.name,
        "structured": experience.structured,
        **summary,
    }


def list_business_experiences(business_id, limit=20):
    record = Business.objects.filter(
        pk=business_id,
        active=True,
    ).first()
    if record is None:
        raise ValueError("ARABA 상점 정보를 찾지 못했습니다.")

    safe_limit = max(1, min(int(limit or 20), 50))
    items = record.experiences.all()[:safe_limit]
    return {
        "business_id": record.id,
        "business_name": record.name,
        **_experience_summary(record),
        "experiences": [
            {
                "id": item.id,
                "text": item.raw_text,
                "structured": item.structured,
                "rating": item.rating,
                "verified_visit": item.verified_visit,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
    }

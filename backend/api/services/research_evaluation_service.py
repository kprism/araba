def _text(value):
    return str(value or "").strip()


def _naver_map(business):
    value = business.get("naver")
    return value if isinstance(value, dict) else {}


def _has_any_business_value(
    businesses,
    key,
):
    return any(
        _text(item.get(key))
        for item in businesses
        if isinstance(item, dict)
    )


def _has_verified_price(
    businesses,
):
    for item in businesses:
        if not isinstance(item, dict):
            continue

        if item.get("verified_total_price") is not None:
            return True

        naver = _naver_map(item)
        prices = naver.get("prices")
        if isinstance(prices, list) and prices:
            return True

    return False


def _has_opening_hours(
    businesses,
):
    for item in businesses:
        if not isinstance(item, dict):
            continue

        naver = _naver_map(item)
        hours = naver.get("opening_hours")
        if isinstance(hours, list) and hours:
            return True

    return False


def _has_availability(
    businesses,
):
    keys = (
        "available_slots",
        "mock_available_slots",
        "verified_available_slots",
    )

    for item in businesses:
        if not isinstance(item, dict):
            continue

        for key in keys:
            value = item.get(key)
            if isinstance(value, list) and value:
                return True

    return False


def _has_stock(
    businesses,
):
    keys = (
        "stock",
        "in_stock",
        "mock_stock",
        "verified_stock",
    )

    for item in businesses:
        if not isinstance(item, dict):
            continue

        if any(
            key in item
            and item.get(key) is not None
            for key in keys
        ):
            return True

    return False


def _has_coordinates(
    businesses,
):
    return any(
        _text(item.get("latitude"))
        and _text(item.get("longitude"))
        for item in businesses
        if isinstance(item, dict)
    )


def _fact_status(
    fact,
    businesses,
    *,
    reference_origin=None,
):
    text = _text(fact).lower()

    if not text:
        return False, "empty_fact"

    if any(
        token in text
        for token in (
            "후보",
            "업체",
            "상점",
            "매장",
            "기관",
            "장소",
        )
    ):
        return bool(businesses), "business_candidates"

    if any(
        token in text
        for token in (
            "주소",
            "위치",
        )
    ):
        return (
            _has_any_business_value(
                businesses,
                "address",
            ),
            "business_address",
        )

    if "전화" in text or "연락처" in text:
        return (
            _has_any_business_value(
                businesses,
                "phone",
            ),
            "business_phone",
        )

    if any(
        token in text
        for token in (
            "거리",
            "이동",
            "가까",
        )
    ):
        return (
            bool(reference_origin)
            and _has_coordinates(businesses),
            "coordinates",
        )

    if any(
        token in text
        for token in (
            "가격",
            "비용",
            "금액",
            "요금",
        )
    ):
        return (
            _has_verified_price(businesses),
            "verified_price",
        )

    if any(
        token in text
        for token in (
            "영업시간",
            "운영시간",
            "영업 여부",
            "영업여부",
        )
    ):
        return (
            _has_opening_hours(businesses),
            "opening_hours",
        )

    if any(
        token in text
        for token in (
            "예약",
            "가능시간",
            "가능 시간",
            "작업 가능",
            "방문 가능",
        )
    ):
        return (
            _has_availability(businesses),
            "live_availability",
        )

    if "재고" in text:
        return (
            _has_stock(businesses),
            "stock",
        )

    # 모르는 사실을 억지로 확인됐다고 보지 않는다.
    return False, "needs_specific_verification"


def _evidence_facts(
    mission,
):
    evidence = mission.get("evidence_needed")
    facts = []

    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            fact = _text(item.get("fact"))
            if fact and fact not in facts:
                facts.append(fact)

    if facts:
        return facts

    required = mission.get("required_facts")
    if isinstance(required, list):
        for item in required:
            fact = _text(item)
            if fact and fact not in facts:
                facts.append(fact)

    return facts


def _next_tools(
    mission,
    missing_facts,
):
    if not missing_facts:
        return []

    tools = []
    evidence = mission.get("evidence_needed")

    if isinstance(evidence, list):
        missing_set = set(missing_facts)

        for item in evidence:
            if not isinstance(item, dict):
                continue
            if _text(item.get("fact")) not in missing_set:
                continue

            priorities = item.get(
                "source_priority"
            )
            if not isinstance(priorities, list):
                continue

            for tool in priorities:
                name = _text(tool)
                if name and name not in tools:
                    tools.append(name)

    if not tools:
        orchestration = mission.get(
            "orchestration"
        )
        if isinstance(orchestration, dict):
            raw = orchestration.get("tools")
            if isinstance(raw, list):
                for tool in raw:
                    name = _text(tool)
                    if (
                        name
                        and name != "place_search"
                        and name not in tools
                    ):
                        tools.append(name)

    if (
        not tools
        and mission.get(
            "may_need_phone_call"
        )
        is True
    ):
        tools.append("phone")

    return tools


def evaluate_research_result(
    mission,
    businesses,
    *,
    reference_origin=None,
):
    safe_businesses = [
        item
        for item in businesses
        if isinstance(item, dict)
    ] if isinstance(businesses, list) else []

    facts = _evidence_facts(mission)
    evidence = []

    for fact in facts:
        confirmed, basis = _fact_status(
            fact,
            safe_businesses,
            reference_origin=reference_origin,
        )
        evidence.append(
            {
                "fact": fact,
                "confirmed": confirmed,
                "basis": basis,
            }
        )

    confirmed_count = sum(
        1
        for item in evidence
        if item["confirmed"]
    )
    total = len(evidence)

    if total == 0:
        coverage = (
            1.0
            if safe_businesses
            else 0.0
        )
    else:
        coverage = confirmed_count / total

    missing = [
        item["fact"]
        for item in evidence
        if not item["confirmed"]
    ]

    if coverage >= 0.85:
        confidence = "high"
    elif coverage >= 0.55:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "answer_ready": (
            bool(safe_businesses)
            and not missing
        ),
        "coverage": round(
            coverage,
            3,
        ),
        "confidence": confidence,
        "confirmed_count": confirmed_count,
        "required_count": total,
        "evidence": evidence,
        "missing_facts": missing,
        "next_tools": _next_tools(
            mission,
            missing,
        ),
        "assessment": (
            "최종 답에 필요한 핵심 사실이 충분히 확인되었습니다."
            if not missing and safe_businesses
            else (
                "후보는 찾았지만 최종 판단에 필요한 사실이 아직 남아 있습니다."
                if safe_businesses
                else "후보 자체를 충분히 확인하지 못했습니다."
            )
        ),
    }

import hashlib
import math
import re


TIME_SLOTS = (
    "오늘 오전",
    "오늘 오후",
    "오늘 저녁",
    "내일 오전",
    "내일 오후",
)


def _stable_number(*parts):
    text = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r)
        * math.cos(lat2_r)
        * math.sin(delta_lon / 2) ** 2
    )
    return radius * 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )


def _reference_origin(businesses, origin=None):
    if isinstance(origin, dict):
        lat = _float(origin.get("latitude"))
        lon = _float(origin.get("longitude"))

        if lat is not None and lon is not None:
            return {
                "latitude": lat,
                "longitude": lon,
                "label": str(
                    origin.get("label") or ""
                ).strip(),
                "source": str(
                    origin.get("source") or "user"
                ).strip(),
                "accuracy": str(
                    origin.get("accuracy") or ""
                ).strip(),
            }

    coordinates = []

    for business in businesses:
        lat = _float(business.get("latitude"))
        lon = _float(business.get("longitude"))

        if lat is None or lon is None:
            continue

        coordinates.append((lat, lon))

    if not coordinates:
        return None

    return {
        "latitude": sum(item[0] for item in coordinates)
        / len(coordinates),
        "longitude": sum(item[1] for item in coordinates)
        / len(coordinates),
        "label": "검색 후보군 중심",
        "source": "candidate_centroid",
        "accuracy": "fallback",
    }


def _mission_text(mission):
    parts = [
        str(mission.get("subject") or ""),
        str(mission.get("comparison") or ""),
        str(mission.get("intent") or ""),
        *[
            str(item)
            for item in (
                mission.get("constraints") or []
            )
        ],
        *[
            str(item)
            for item in (
                mission.get("required_facts") or []
            )
        ],
    ]

    attributes = mission.get("attributes")
    if isinstance(attributes, dict):
        for key, value in attributes.items():
            parts.extend(
                [str(key), str(value)]
            )

    return " ".join(parts)


def _requested_time(mission):
    attributes = mission.get("attributes")

    if isinstance(attributes, dict):
        for key, value in attributes.items():
            key_text = str(key)

            if any(
                token in key_text
                for token in (
                    "시간",
                    "예약",
                    "방문",
                    "일정",
                )
            ):
                text = str(value).strip()

                if text and text not in (
                    "미정",
                    "없음",
                    "null",
                ):
                    return text

    text = _mission_text(mission)

    patterns = (
        r"(오늘\s*(?:오전|오후|저녁))",
        r"(내일\s*(?:오전|오후|저녁))",
        r"(\d{1,2}\s*시(?:\s*~\s*\d{1,2}\s*시)?)",
    )

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    return None


def _price_relevant(mission):
    text = _mission_text(mission)

    return any(
        token in text
        for token in (
            "가격",
            "비용",
            "최저가",
            "경제",
            "견적",
            "금액",
            "결제",
        )
    )


def _question_policy(mission):
    questions = []

    required = mission.get("required_facts")
    if isinstance(required, list):
        for item in required:
            value = str(item).strip()
            if value and value not in questions:
                questions.append(value)

    defaults = [
        "현재 실제 이용 또는 예약 가능 여부",
        "추가비용까지 포함한 최종 조건",
        "가능한 시간대와 예상 소요시간",
        "취소·변경·보증 등 선택에 영향을 주는 조건",
    ]

    for item in defaults:
        if item not in questions:
            questions.append(item)

    return questions[:7]


def _available_slots(seed):
    slots = [
        slot
        for index, slot in enumerate(TIME_SLOTS)
        if ((seed >> index) & 1) == 1
    ]

    if not slots:
        slots = [
            TIME_SLOTS[
                seed % len(TIME_SLOTS)
            ]
        ]

    return slots[:3]


def _slot_matches(requested, slots):
    if not requested:
        return True

    normalized = re.sub(
        r"\s+",
        "",
        requested,
    )

    for slot in slots:
        candidate = re.sub(
            r"\s+",
            "",
            slot,
        )

        if (
            normalized in candidate
            or candidate in normalized
        ):
            return True

    return False


def _answer_for_fact(
    fact,
    *,
    total_price,
    slots,
    wait_minutes,
    work_minutes,
):
    fact_text = str(fact)

    if any(
        token in fact_text
        for token in (
            "가격",
            "비용",
            "금액",
            "결제",
            "견적",
        )
    ):
        if total_price is None:
            return (
                "가상 답변: 이 요청에서는 가격이 "
                "핵심 비교항목이 아닌 것으로 가정."
            )

        return (
            f"가상 답변: 최종 조건 기준 "
            f"{total_price:,}원."
        )

    if any(
        token in fact_text
        for token in (
            "시간",
            "예약",
            "가능",
            "일정",
        )
    ):
        return (
            "가상 답변: 가능한 시간대 "
            + ", ".join(slots)
            + f", 예상 대기 {wait_minutes}분."
        )

    if any(
        token in fact_text
        for token in (
            "취소",
            "변경",
            "환불",
            "보증",
        )
    ):
        return (
            "가상 답변: 변경 가능, 취소나 특수조건은 "
            "예약 확정 전에 다시 안내하는 것으로 가정."
        )

    return (
        f"가상 답변: {fact_text}에 대해 "
        "선택에 필요한 핵심 조건을 확인한 것으로 가정."
    )


def _mock_business_call(
    mission,
    business,
    origin,
):
    seed = _stable_number(
        business.get("id"),
        business.get("name"),
        mission.get("subject"),
        mission.get("category"),
    )

    # 가격은 실제 출처에서 확인된 값만 사용한다.
    # 카카오 Local API에는 가격표가 없으므로 POC에서 임의 가격을 생성하지 않는다.
    verified_price = business.get("verified_total_price")
    total_price = (
        int(verified_price)
        if isinstance(verified_price, (int, float))
        else None
    )

    wait_minutes = 5 + (seed % 8) * 10
    work_minutes = 15 + (seed % 7) * 15
    available_slots = _available_slots(seed)
    requested_time = _requested_time(mission)

    requested_time_available = _slot_matches(
        requested_time,
        available_slots,
    )

    lat = _float(
        business.get("latitude")
    )
    lon = _float(
        business.get("longitude")
    )

    distance_km = None

    if (
        origin is not None
        and lat is not None
        and lon is not None
    ):
        distance_km = round(
            _haversine_km(
                origin["latitude"],
                origin["longitude"],
                lat,
                lon,
            ),
            1,
        )

    drive_minutes = (
        max(
            5,
            round(
                distance_km / 28 * 60
            ),
        )
        if distance_km is not None
        else None
    )

    round_trip_minutes = (
        drive_minutes * 2
        if drive_minutes is not None
        else 0
    )

    round_trip_distance = (
        distance_km * 2
        if distance_km is not None
        else 0
    )

    total_time_minutes = (
        round_trip_minutes
        + wait_minutes
        + work_minutes
    )

    distance_cost = round(
        round_trip_distance * 250
    )

    time_cost = round(
        (total_time_minutes / 60)
        * 10000
    )

    availability_penalty = (
        0
        if requested_time_available
        else 150000
    )

    price_component = total_price

    comparison = str(
        mission.get("comparison") or ""
    )

    if (
        "최저" in comparison
        or "가격" in comparison
    ):
        time_weight = 0.5
    elif (
        "빠른" in comparison
        or "시간" in comparison
    ):
        time_weight = 1.7
    else:
        time_weight = 1.0

    effective_cost = (
        round(
            price_component
            + distance_cost
            + time_cost * time_weight
            + availability_penalty
        )
        if price_component is not None
        else None
    )

    efficiency_score = round(
        distance_cost
        + time_cost * time_weight
        + availability_penalty
    )

    questions = _question_policy(mission)

    qa = [
        {
            "question": fact,
            "answer": _answer_for_fact(
                fact,
                total_price=total_price,
                slots=available_slots,
                wait_minutes=wait_minutes,
                work_minutes=work_minutes,
            ),
        }
        for fact in questions
    ]

    result = dict(business)

    result.update(
        {
            "mock": True,
            "mock_call_result": (
                "가상 통화 테스트 결과입니다. "
                "실제 가격·재고·예약 결과가 아닙니다."
            ),
            "mock_questions": qa,
            "mock_total_price": total_price,
            "mock_available_slots": available_slots,
            "mock_requested_time": requested_time,
            "mock_requested_time_available": (
                requested_time_available
            ),
            "mock_wait_minutes": wait_minutes,
            "mock_work_minutes": work_minutes,
            "distance_km": distance_km,
            "drive_minutes": drive_minutes,
            "round_trip_minutes": (
                round_trip_minutes
            ),
            "total_time_minutes": (
                total_time_minutes
            ),
            "distance_cost_estimate": (
                distance_cost
            ),
            "time_cost_estimate": time_cost,
            "effective_cost": effective_cost,
            "efficiency_score": efficiency_score,
        }
    )

    return result


def simulate_mock_calls(
    mission,
    businesses,
    origin=None,
):
    if not isinstance(mission, dict):
        raise ValueError(
            "조사 Mission 정보가 필요합니다."
        )

    if (
        not isinstance(businesses, list)
        or not businesses
    ):
        raise ValueError(
            "가상 통화할 실제 업체 목록이 필요합니다."
        )

    safe_businesses = [
        dict(item)
        for item in businesses
        if isinstance(item, dict)
    ][:8]

    if not safe_businesses:
        raise ValueError(
            "가상 통화할 실제 업체 목록이 필요합니다."
        )

    resolved_origin = _reference_origin(
        safe_businesses,
        origin=origin,
    )

    called = [
        _mock_business_call(
            mission,
            business,
            resolved_origin,
        )
        for business in safe_businesses
    ]

    called.sort(
        key=lambda item: (
            not item.get(
                "mock_requested_time_available",
                False,
            ),
            item.get(
                "effective_cost",
            )
            if item.get(
                "effective_cost"
            ) is not None
            else item.get(
                "efficiency_score",
                10**12,
            ),
            item.get("mock_total_price")
            if item.get(
                "mock_total_price"
            ) is not None
            else 10**12,
        )
    )

    for index, item in enumerate(
        called,
        start=1,
    ):
        item["economic_rank"] = index

    best = called[0]

    requested_time = _requested_time(
        mission
    )

    available_slots = (
        best.get(
            "mock_available_slots"
        )
        or []
    )

    slot_text = (
        ", ".join(available_slots)
        or "확인 필요"
    )

    price = best.get(
        "mock_total_price"
    )

    price_text = (
        f"{price:,}원"
        if isinstance(
            price,
            (int, float),
        )
        else "실제 가격 미확인"
    )

    distance_text = (
        f"{best['distance_km']:.1f}km"
        if best.get(
            "distance_km"
        ) is not None
        else "거리 계산 불가"
    )

    drive_text = (
        f"차량 약 "
        f"{best['drive_minutes']}분"
        if best.get(
            "drive_minutes"
        ) is not None
        else "이동시간 계산 불가"
    )

    origin_label = (
        resolved_origin.get("label")
        if isinstance(
            resolved_origin,
            dict,
        )
        else None
    )

    origin_source = (
        resolved_origin.get("source")
        if isinstance(
            resolved_origin,
            dict,
        )
        else None
    )

    if (
        origin_source
        == "user_search_region"
    ):
        basis = (
            "실제 업체 위치 + 가상 전화 응답을 이용한 "
            "POC 비교입니다. 거리와 이동시간은 "
            f"사용자가 지정한 검색 지역 "
            f"{origin_label or ''} 기준의 "
            "대략적인 추정치입니다."
        )
    else:
        basis = (
            "실제 업체 위치 + 가상 전화 응답을 이용한 "
            "POC 비교입니다. 정확한 사용자 출발 좌표가 없어 "
            "후보군 중심을 임시 기준으로 사용했습니다."
        )

    if requested_time:
        schedule_reason = (
            f"희망시간 {requested_time} "
            "가능 여부를 우선 반영했습니다."
        )
    else:
        schedule_reason = (
            "희망시간이 정해지지 않아 "
            "업체가 제시한 가능시간 "
            f"{slot_text}을 사용자 선택용으로 "
            "함께 제공합니다."
        )

    return {
        "mock": True,
        "basis": basis,
        "reference_origin": resolved_origin,
        "businesses": called,
        "recommendation": {
            "business_id": best.get("id"),
            "name": best.get("name"),
            "mock_total_price": price,
            "available_slots": (
                available_slots
            ),
            "requested_time": (
                requested_time
            ),
            "requested_time_available": (
                best.get(
                    "mock_requested_time_available"
                )
            ),
            "distance_km": best.get(
                "distance_km"
            ),
            "drive_minutes": best.get(
                "drive_minutes"
            ),
            "total_time_minutes": (
                best.get(
                    "total_time_minutes"
                )
            ),
            "distance_cost_estimate": (
                best.get(
                    "distance_cost_estimate"
                )
            ),
            "time_cost_estimate": (
                best.get(
                    "time_cost_estimate"
                )
            ),
            "effective_cost": best.get(
                "effective_cost"
            ),
            "efficiency_score": best.get(
                "efficiency_score"
            ),
            "reason": (
                f"가상 통화 기준 {price_text}, "
                f"{distance_text}, {drive_text}, "
                "대기·처리시간과 예약 가능성을 함께 반영했을 때 "
                "현재 후보 중 목표 달성 효율이 가장 높습니다. "
                f"{schedule_reason}"
            ),
        },
        "question_policy": (
            _question_policy(mission)
        ),
    }

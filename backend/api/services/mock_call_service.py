import hashlib
import math
import re


def _stable_number(*parts):
    text = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _quantity_from_mission(mission):
    chunks = [
        str(mission.get("subject") or ""),
        *[
            str(item)
            for item in (mission.get("constraints") or [])
        ],
    ]
    text = " ".join(chunks)

    match = re.search(r"(\d+)\s*(?:개|짝|본)", text)
    if match:
        return max(1, min(4, int(match.group(1))))

    korean_counts = {
        "한 개": 1,
        "하나": 1,
        "두 개": 2,
        "둘": 2,
        "네 개": 4,
        "넷": 4,
    }
    for token, value in korean_counts.items():
        if token in text:
            return value

    return 2


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


def _reference_origin(businesses):
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
    }


def _mock_tire_call(mission, business, origin):
    quantity = _quantity_from_mission(mission)
    seed = _stable_number(
        business.get("id"),
        business.get("name"),
        mission.get("subject"),
        quantity,
    )

    unit_price = 165000 + (seed % 16) * 8500
    fitting_fee = quantity * (12000 + (seed % 4) * 2500)
    balance_fee = quantity * (5000 + (seed % 3) * 1500)
    disposal_fee = quantity * 3000
    total_price = (
        quantity * unit_price
        + fitting_fee
        + balance_fee
        + disposal_fee
    )

    stock = (seed % 7) != 0
    wait_minutes = 15 + (seed % 7) * 10
    work_minutes = 35 + (seed % 5) * 10

    lat = _float(business.get("latitude"))
    lon = _float(business.get("longitude"))
    distance_km = None

    if origin is not None and lat is not None and lon is not None:
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
        max(5, round(distance_km / 28 * 60))
        if distance_km is not None
        else None
    )

    round_trip_distance = (
        distance_km * 2
        if distance_km is not None
        else 0
    )
    round_trip_minutes = (
        drive_minutes * 2
        if drive_minutes is not None
        else 0
    )

    travel_cost = round(
        round_trip_distance * 250
        + (round_trip_minutes / 60) * 10000
    )
    availability_penalty = 0 if stock else 120000
    effective_cost = (
        total_price
        + travel_cost
        + availability_penalty
    )

    model_index = seed % 4
    mock_models = [
        "프리미엄 컴포트",
        "고성능 투어링",
        "SUV 컴포트",
        "올시즌 퍼포먼스",
    ]
    mock_model = mock_models[model_index]

    qa = [
        {
            "question": (
                f"요청한 타이어 {quantity}개를 오늘 "
                "교체할 수 있나요?"
            ),
            "answer": (
                f"가상 답변: {'재고 있음' if stock else '현재 재고 없음'}, "
                f"예상 대기 {wait_minutes}분."
            ),
        },
        {
            "question": (
                "장착비, 휠밸런스, 폐타이어 처리비까지 "
                "모두 포함한 최종 결제금액은 얼마인가요?"
            ),
            "answer": (
                f"가상 답변: 총 {total_price:,}원 "
                "(부대비용 포함)."
            ),
        },
        {
            "question": (
                "재고 타이어의 모델과 제조 상태, "
                "추가 비용 가능성이 있나요?"
            ),
            "answer": (
                f"가상 답변: {mock_model} 계열 재고, "
                "별도 추가비용 없음으로 가정."
            ),
        },
        {
            "question": "도착 후 실제 작업에는 얼마나 걸리나요?",
            "answer": (
                f"가상 답변: 약 {work_minutes}분."
            ),
        },
    ]

    result = dict(business)
    result.update(
        {
            "mock": True,
            "mock_call_result": (
                "가상 통화 테스트 결과입니다. 실제 가격·재고가 아닙니다."
            ),
            "mock_questions": qa,
            "mock_total_price": total_price,
            "mock_stock": stock,
            "mock_wait_minutes": wait_minutes,
            "mock_work_minutes": work_minutes,
            "distance_km": distance_km,
            "drive_minutes": drive_minutes,
            "travel_cost_estimate": travel_cost,
            "effective_cost": effective_cost,
            "quantity": quantity,
        }
    )
    return result


def simulate_mock_calls(mission, businesses):
    if not isinstance(mission, dict):
        raise ValueError("조사 Mission 정보가 필요합니다.")
    if not isinstance(businesses, list) or not businesses:
        raise ValueError("가상 통화할 실제 업체 목록이 필요합니다.")

    category = str(
        mission.get("category") or "기타"
    ).strip()
    subject = str(
        mission.get("subject") or ""
    ).lower()

    if category != "자동차" or "타이어" not in subject:
        raise ValueError(
            "현재 POC 가상 통화 최적화는 자동차 타이어 조사부터 지원합니다."
        )

    safe_businesses = [
        dict(item)
        for item in businesses
        if isinstance(item, dict)
    ][:8]

    origin = _reference_origin(safe_businesses)

    called = [
        _mock_tire_call(
            mission,
            business,
            origin,
        )
        for business in safe_businesses
    ]

    called.sort(
        key=lambda item: (
            not item.get("mock_stock", False),
            item.get("effective_cost", 10**12),
            item.get("mock_total_price", 10**12),
        )
    )

    for index, item in enumerate(called, start=1):
        item["economic_rank"] = index

    best = called[0]
    distance_text = (
        f"{best['distance_km']:.1f}km"
        if best.get("distance_km") is not None
        else "거리 계산 불가"
    )
    time_text = (
        f"차량 약 {best['drive_minutes']}분"
        if best.get("drive_minutes") is not None
        else "이동시간 계산 불가"
    )

    return {
        "mock": True,
        "basis": (
            "실제 업체 위치 + 가상 전화 견적을 이용한 POC 비교입니다. "
            "거리와 이동시간은 검색된 후보군의 지리적 중심을 기준으로 한 추정치입니다."
        ),
        "businesses": called,
        "recommendation": {
            "business_id": best.get("id"),
            "name": best.get("name"),
            "mock_total_price": best.get("mock_total_price"),
            "distance_km": best.get("distance_km"),
            "drive_minutes": best.get("drive_minutes"),
            "effective_cost": best.get("effective_cost"),
            "reason": (
                f"가상 총액 {best['mock_total_price']:,}원, "
                f"{distance_text}, {time_text}을 함께 반영했을 때 "
                "현재 후보 중 시간·이동비용까지 포함한 경제성 비용이 가장 낮습니다."
            ),
        },
        "question_policy": [
            "요청 규격·수량의 실제 재고와 당일 교체 가능 여부",
            "장착비·휠밸런스·폐기비·부가세를 포함한 최종 결제금액",
            "타이어 모델·제조 상태·추가비용 가능성",
            "대기시간과 실제 작업시간",
        ],
    }

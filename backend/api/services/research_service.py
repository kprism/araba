import os

import httpx


KAKAO_LOCAL_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/keyword.json"
)
KAKAO_ADDRESS_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/address.json"
)


class ResearchConfigurationError(ValueError):
    pass


class ResearchProviderError(RuntimeError):
    pass


def _kakao_rest_api_key():
    return str(
        os.environ.get("KAKAO_REST_API_KEY", "")
    ).strip()


def _life_info_for(category):
    if category == "자동차":
        return [
            "타이어나 정비 비용은 장착비, 휠밸런스, 폐기 비용이 별도인지 확인하면 실제 결제금액을 비교하기 쉽습니다.",
            "타이어는 규격뿐 아니라 제조주차와 재고 상태도 함께 확인하는 게 좋습니다.",
        ]

    if category == "예약":
        return [
            "예약 가능 여부뿐 아니라 취소 규정과 변경 가능 시간을 같이 확인하면 일정 변경 때 편합니다.",
            "예약 확정 전 최종 금액과 포함 항목을 한 번 더 확인하는 게 좋습니다.",
        ]

    if category == "의료":
        return [
            "진료 가능 시간과 함께 초진 접수 마감시간, 준비해야 할 서류가 있는지 확인하면 헛걸음을 줄일 수 있습니다.",
            "비급여 항목은 기관별 차이가 있을 수 있어 최종 비용을 직접 확인하는 게 좋습니다.",
        ]

    return [
        "표시 가격만 보지 말고 추가비용과 당일 이용 가능 여부를 같이 확인하면 실제 선택이 쉬워집니다.",
        "후기보다 현재 재고, 운영시간, 예약 가능 여부처럼 변할 수 있는 정보는 직접 확인하는 게 안전합니다.",
    ]


def _location_address_query(location):
    normalized = " ".join(
        str(location or "").split()
    ).strip()

    if (
        normalized
        and " " not in normalized
        and not normalized.endswith(
            ("시", "군", "구", "도")
        )
    ):
        return f"{normalized}시"

    return normalized


def _resolve_location_origin(location, api_key):
    query = _location_address_query(location)
    if not query:
        return None

    try:
        response = httpx.get(
            KAKAO_ADDRESS_SEARCH_URL,
            headers={
                "Authorization": f"KakaoAK {api_key}",
            },
            params={
                "query": query,
                "size": 1,
            },
            timeout=httpx.Timeout(
                2.0,
                connect=1.0,
            ),
        )
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None

    payload = response.json()
    documents = payload.get("documents", [])
    if not isinstance(documents, list) or not documents:
        return None

    document = documents[0]
    if not isinstance(document, dict):
        return None

    latitude = str(document.get("y") or "").strip()
    longitude = str(document.get("x") or "").strip()

    if not latitude or not longitude:
        return None

    address = document.get("address")
    label = query
    if isinstance(address, dict):
        address_name = str(
            address.get("address_name") or ""
        ).strip()
        if address_name:
            label = address_name

    return {
        "label": label,
        "latitude": latitude,
        "longitude": longitude,
        "source": "user_search_region",
        "accuracy": "region_reference",
    }


def _location_variants(location):
    normalized = " ".join(
        str(location or "").split()
    ).strip()

    if not normalized:
        return [""]

    parts = normalized.split(" ")
    variants = [normalized]

    # "창원시 의창구"처럼 세부 지역이 들어오면
    # 결과가 없을 때 "창원시"까지 자동으로 넓혀 찾는다.
    for length in range(len(parts) - 1, 0, -1):
        candidate = " ".join(parts[:length]).strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    return variants


def _search_queries(mission):
    location = str(
        mission.get("location") or ""
    ).strip()
    subject = str(
        mission.get("subject") or ""
    ).strip()
    category = str(
        mission.get("category") or "기타"
    ).strip()

    subject_lower = subject.lower()
    generic_subject = subject

    if category == "자동차":
        if "타이어" in subject_lower:
            generic_subject = "타이어"
        elif any(
            token in subject_lower
            for token in ("정비", "수리", "카센터")
        ):
            generic_subject = "자동차정비"

    queries = []

    # 카카오 장소검색은 자연어 조건 전체보다
    # "지역 + 업종" 형태가 훨씬 안정적이다.
    # 가장 성공률 높은 짧은 검색어를 먼저 보낸다.
    for location_variant in _location_variants(location):
        for candidate_subject in (generic_subject, subject):
            query = " ".join(
                part
                for part in (
                    location_variant,
                    candidate_subject,
                )
                if part
            ).strip()

            if query and query not in queries:
                queries.append(query)

    if not queries:
        raise ResearchConfigurationError(
            "실제 업체 검색에 사용할 지역 또는 대상 정보가 부족합니다."
        )

    return queries[:6]

def _matches_mission(document, mission):
    category = str(
        mission.get("category") or "기타"
    ).strip()
    subject = str(
        mission.get("subject") or ""
    ).lower()
    place_name = str(
        document.get("place_name") or ""
    ).lower()
    place_category = str(
        document.get("category_name") or ""
    ).lower()

    if category == "자동차":
        allowed_tokens = (
            "자동차",
            "타이어",
            "정비",
            "카센터",
            "휠",
        )
        if not any(
            token in place_category or token in place_name
            for token in allowed_tokens
        ):
            return False

        if "타이어" in subject and not any(
            token in place_category or token in place_name
            for token in ("타이어", "휠", "자동차정비", "카센터")
        ):
            return False

    return True


def _normalize_business(document):
    road_address = str(
        document.get("road_address_name") or ""
    ).strip()
    address = str(
        document.get("address_name") or ""
    ).strip()
    category = str(
        document.get("category_name") or ""
    ).strip()
    category_leaf = (
        category.split(">")[-1].strip()
        if category
        else "업체"
    )

    return {
        "id": str(document.get("id") or "").strip(),
        "name": str(
            document.get("place_name") or ""
        ).strip(),
        "description": category_leaf,
        "category": category,
        "address": road_address or address,
        "road_address": road_address,
        "lot_address": address,
        "phone": str(
            document.get("phone") or ""
        ).strip(),
        "place_url": str(
            document.get("place_url") or ""
        ).strip(),
        "longitude": str(
            document.get("x") or ""
        ).strip(),
        "latitude": str(
            document.get("y") or ""
        ).strip(),
        "image_url": None,
        "source": "kakao",
    }


def search_real_businesses(mission, api_key=None):
    resolved_api_key = str(api_key or "").strip()
    if not resolved_api_key:
        resolved_api_key = _kakao_rest_api_key()

    if not resolved_api_key:
        raise ResearchConfigurationError(
            "MY의 관리자 API 설정에서 Kakao REST API Key를 먼저 등록해주세요."
        )

    last_error = None
    selected_query = None
    documents = []

    for query in _search_queries(mission):
        selected_query = query

        try:
            response = httpx.get(
                KAKAO_LOCAL_SEARCH_URL,
                headers={
                    "Authorization": f"KakaoAK {resolved_api_key}",
                },
                params={
                    "query": query,
                    "size": 8,
                },
                timeout=httpx.Timeout(
                    5.0,
                    connect=2.0,
                ),
            )
        except httpx.HTTPError as exc:
            last_error = exc
            continue

        if response.status_code != 200:
            raise ResearchProviderError(
                "카카오 장소검색 요청에 실패했습니다. "
                f"HTTP {response.status_code}"
            )

        payload = response.json()
        raw_documents = payload.get("documents", [])

        if isinstance(raw_documents, list):
            documents = [
                item
                for item in raw_documents
                if isinstance(item, dict)
                and _matches_mission(item, mission)
            ]

        if documents:
            break

    if not documents and last_error is not None:
        raise ResearchProviderError(
            "카카오 장소검색 서버에 연결하지 못했습니다."
        ) from last_error

    businesses = [
        business
        for business in (
            _normalize_business(item)
            for item in documents
            if isinstance(item, dict)
        )
        if business["name"]
    ]

    category = str(
        mission.get("category") or "기타"
    ).strip()

    reference_origin = _resolve_location_origin(
        mission.get("location"),
        resolved_api_key,
    )

    return {
        "source": "kakao",
        "search_query": selected_query,
        "businesses": businesses,
        "reference_origin": reference_origin,
        "life_info": _life_info_for(category),
        "phone_call_mock": True,
        "final_question": (
            "실제 통화 기능이 연결되면 이 업체에 예약을 진행할까요?"
        ),
        "actions": ["예약하기", "다른 후보 보기", "여기까지"],
    }

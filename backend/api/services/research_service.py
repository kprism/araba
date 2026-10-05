import os

import httpx


KAKAO_LOCAL_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/keyword.json"
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

    queries = []

    primary = " ".join(
        part for part in (location, subject) if part
    ).strip()
    if primary:
        queries.append(primary)

    if category == "자동차":
        subject_lower = subject.lower()
        if "타이어" in subject_lower:
            fallback = " ".join(
                part for part in (location, "타이어") if part
            ).strip()
            if fallback and fallback not in queries:
                queries.append(fallback)
        elif any(
            token in subject_lower
            for token in ("정비", "수리", "카센터")
        ):
            fallback = " ".join(
                part for part in (location, "자동차정비") if part
            ).strip()
            if fallback and fallback not in queries:
                queries.append(fallback)

    if not queries:
        raise ResearchConfigurationError(
            "실제 업체 검색에 사용할 지역 또는 대상 정보가 부족합니다."
        )

    return queries


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
                    "size": 5,
                },
                timeout=10.0,
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
            documents = raw_documents

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

    return {
        "source": "kakao",
        "search_query": selected_query,
        "businesses": businesses,
        "life_info": _life_info_for(category),
        "phone_call_mock": True,
        "final_question": (
            "실제 통화 기능이 연결되면 이 업체에 예약을 진행할까요?"
        ),
        "actions": ["예약하기", "다른 후보 보기", "여기까지"],
    }

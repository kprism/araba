import math
import os
import re

import httpx

from .kakao_place_service import enrich_businesses_with_kakao_pages
from .naver_place_service import enrich_businesses_with_naver
from .openai_place_enrichment_service import (
    enrich_businesses_with_openai_web,
)
from .web_place_enrichment_service import enrich_businesses_with_web
from .research_evaluation_service import (
    evaluate_research_result,
)
from .business_matching_service import match_businesses
from .business_agent_service import (
    enrich_businesses_with_agents,
)
from .google_places_service import (
    enrich_businesses_with_google_places,
)
from .image_identity_service import (
    enforce_business_images,
)
from .temporal_service import (
    annotate_businesses_now,
    current_time_context,
)

from .business_graph_service import (
    cached_businesses_for_mission,
    merge_businesses_from_graph,
    persist_businesses,
)


KAKAO_LOCAL_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/keyword.json"
)
KAKAO_ADDRESS_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/address.json"
)

# 첫 응답을 상세검증 전체에 묶어두면 모바일 조회 타임아웃이 발생할 수 있다.
# 상위 후보만 빠르게 상세검증하고 나머지는 후보 자체를 먼저 반환한다.
FAST_DETAIL_ENRICH_LIMIT = 5
MAX_KAKAO_QUERY_ATTEMPTS = 5

STRICT_FOOD_KEYWORDS = {
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


def _place_identity_text(value):
    return re.sub(
        r"[^0-9a-zA-Z가-힣]+",
        "",
        str(value or ""),
    ).replace("특례", "").lower()


def _edit_distance(left, right):
    a = str(left or "")
    b = str(right or "")
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1]
                    + (0 if char_a == char_b else 1),
                )
            )
        previous = current
    return previous[-1]


def _administrative_tokens(value):
    raw_tokens = re.findall(
        r"[가-힣]+",
        str(value or ""),
    )
    suffixes = (
        "특별시",
        "광역시",
        "특별자치시",
        "특별자치도",
        "도",
        "시",
        "군",
        "구",
        "읍",
        "면",
        "동",
        "리",
    )
    return [
        token
        for token in raw_tokens
        if token.endswith(suffixes)
    ]


def _fuzzy_admin_document_match(query, document):
    query_tokens = _administrative_tokens(query)
    if not query_tokens:
        return None

    address_text = " ".join(
        [
            str(document.get("address_name") or ""),
            str(document.get("road_address_name") or ""),
        ]
    ).strip()
    address_tokens = _administrative_tokens(
        address_text
    )
    if not address_tokens:
        return None

    query_leaf = query_tokens[-1]
    address_leaf_candidates = [
        token
        for token in address_tokens
        if token.endswith(
            ("읍", "면", "동", "리")
        )
    ]
    if not address_leaf_candidates:
        return None

    parent_query = query_tokens[:-1]
    parent_haystack = set(address_tokens)
    if parent_query and not all(
        token in parent_haystack
        for token in parent_query
    ):
        return None

    best_leaf = min(
        address_leaf_candidates,
        key=lambda token: _edit_distance(
            query_leaf,
            token,
        ),
    )
    if _edit_distance(
        query_leaf,
        best_leaf,
    ) > 1:
        return None

    corrected_tokens = []
    for token in address_tokens:
        if token not in corrected_tokens:
            corrected_tokens.append(token)

    return {
        "label": " ".join(corrected_tokens),
        "leaf": best_leaf,
    }


def _fuzzy_recovery_queries(
    query,
    mission=None,
):
    queries = [query]
    tokens = _administrative_tokens(query)
    if len(tokens) < 2:
        return queries

    parent = " ".join(tokens[:-1]).strip()
    raw_terms = (
        mission.get("search_terms")
        if isinstance(mission, dict)
        else None
    )
    terms = (
        [
            str(item).strip()
            for item in raw_terms
            if str(item).strip()
        ]
        if isinstance(raw_terms, list)
        else []
    )

    if isinstance(mission, dict):
        for value in (
            mission.get("subject"),
            mission.get("category"),
        ):
            text = str(value or "").strip()
            if text and text not in terms:
                terms.append(text)

    for term in terms[:3]:
        for variant in _compact_term_variants(term):
            candidate = f"{parent} {variant}".strip()
            if candidate not in queries:
                queries.append(candidate)
            if len(queries) >= 5:
                return queries

    if parent and parent not in queries:
        queries.append(parent)
    return queries[:5]


def _resolve_fuzzy_admin_origin(
    location,
    api_key,
    mission=None,
):
    query = " ".join(
        str(location or "").split()
    ).strip()
    if not query:
        return None

    query_tokens = _administrative_tokens(query)
    if not query_tokens:
        return None

    for recovery_query in _fuzzy_recovery_queries(
        query,
        mission,
    ):
        try:
            response = httpx.get(
                KAKAO_LOCAL_SEARCH_URL,
                headers={
                    "Authorization": f"KakaoAK {api_key}",
                },
                params={
                    "query": recovery_query,
                    "size": 15,
                },
                timeout=httpx.Timeout(
                    3.0,
                    connect=1.5,
                ),
            )
        except httpx.HTTPError:
            continue

        if response.status_code != 200:
            continue

        payload = response.json()
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            continue

        matches = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            fuzzy = _fuzzy_admin_document_match(
                query,
                document,
            )
            if fuzzy is None:
                continue

            latitude = str(
                document.get("y") or ""
            ).strip()
            longitude = str(
                document.get("x") or ""
            ).strip()
            if not latitude or not longitude:
                continue

            distance = _edit_distance(
                query_tokens[-1],
                fuzzy["leaf"],
            )
            matches.append(
                (
                    distance,
                    fuzzy["leaf"],
                    fuzzy,
                    latitude,
                    longitude,
                )
            )

        if not matches:
            continue

        matches.sort(
            key=lambda item: (
                item[0],
                item[1],
            )
        )
        best_distance = matches[0][0]
        best_leaves = {
            item[1]
            for item in matches
            if item[0] == best_distance
        }
        if len(best_leaves) != 1:
            continue

        _, _, fuzzy, latitude, longitude = matches[0]
        return {
            "label": fuzzy["label"],
            "latitude": latitude,
            "longitude": longitude,
            "source": "fuzzy_admin_recovery",
            "accuracy": "region_reference",
            "spoken_location": query,
            "corrected_leaf": fuzzy["leaf"],
        }

    return None


def _resolve_reference_point_origin(
    reference_point,
    api_key,
):
    query = " ".join(
        str(reference_point or "").split()
    ).strip()
    if not query:
        return None

    try:
        response = httpx.get(
            KAKAO_LOCAL_SEARCH_URL,
            headers={
                "Authorization": f"KakaoAK {api_key}",
            },
            params={
                "query": query,
                "size": 1,
            },
            timeout=httpx.Timeout(
                3.0,
                connect=1.5,
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

    query_identity = _place_identity_text(query)
    place_identity = _place_identity_text(
        document.get("place_name")
    )
    identity_haystack = _place_identity_text(
        " ".join(
            [
                str(document.get("place_name") or ""),
                str(document.get("road_address_name") or ""),
                str(document.get("address_name") or ""),
            ]
        )
    )
    if (
        query_identity
        and query_identity not in identity_haystack
        and (
            not place_identity
            or place_identity not in query_identity
        )
    ):
        return None

    latitude = str(document.get("y") or "").strip()
    longitude = str(document.get("x") or "").strip()
    if not latitude or not longitude:
        return None

    return {
        "label": (
            str(
                document.get("place_name")
                or query
            ).strip()
            or query
        ),
        "latitude": latitude,
        "longitude": longitude,
        "source": "reference_point",
        "accuracy": "place_reference",
        "address": str(
            document.get("road_address_name")
            or document.get("address_name")
            or ""
        ).strip(),
    }


REFERENCE_POINT_SUFFIXES = (
    "시청",
    "군청",
    "구청",
    "청사",
    "주민센터",
    "행정복지센터",
    "역",
    "공항",
    "터미널",
    "병원",
    "학교",
    "대학교",
    "공원",
    "시장",
    "호텔",
    "아파트",
    "백화점",
    "마트",
    "도서관",
    "경찰서",
    "소방서",
    "법원",
    "체육관",
    "경기장",
    "항",
    "항구",
)


def _location_address_candidates(location):
    normalized = " ".join(
        str(location or "").split()
    ).strip()
    if not normalized:
        return []

    # 명백한 시설/기준장소 이름에는 행정구역 접미사를 붙이지 않는다.
    # 예: 창원시청 -> 창원시청시(X), 서울역 -> 서울역시(X)
    if normalized.endswith(
        REFERENCE_POINT_SUFFIXES
    ):
        return [normalized]

    fallback = _location_address_query(normalized)
    candidates = []

    # "창원"처럼 기존에 정상 동작하던 짧은 행정구역 입력은
    # "창원시"를 먼저 시도해 호환성을 유지한다.
    if fallback:
        candidates.append(fallback)
    if normalized not in candidates:
        candidates.append(normalized)

    return candidates


def _resolve_location_origin(
    location,
    api_key,
    mission=None,
):
    normalized = " ".join(
        str(location or "").split()
    ).strip()
    if not normalized:
        return None

    # 먼저 사용자가 실제로 말한 문자열을 그대로 주소검색한다.
    # "창원시청" 같은 기준 장소를 임의로 "창원시청시"로 바꾼 뒤
    # 검색을 시작하면 주변검색의 기준점을 잃을 수 있다.
    for query in _location_address_candidates(
        normalized
    ):
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
            continue

        if response.status_code != 200:
            continue

        payload = response.json()
        documents = payload.get(
            "documents",
            [],
        )
        if (
            not isinstance(documents, list)
            or not documents
        ):
            continue

        document = documents[0]
        if not isinstance(document, dict):
            continue

        latitude = str(
            document.get("y") or ""
        ).strip()
        longitude = str(
            document.get("x") or ""
        ).strip()

        if not latitude or not longitude:
            continue

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

    # 음성인식에서 행정동 한 글자가 비슷하게 잘못 들어온 경우
    # 상위 시/구가 일치하고 하위 읍/면/동/리가 한 글자 차이면
    # Kakao 결과의 실제 주소로 안전하게 교정한다.
    fuzzy_admin = _resolve_fuzzy_admin_origin(
        normalized,
        api_key,
        mission=mission,
    )
    if fuzzy_admin is not None:
        return fuzzy_admin

    # 주소가 아니었던 문자열은 장소명일 수 있다.
    # Mission 분류가 administrative_area로 잘못 와도
    # 장소검색으로 한 번 더 해석해 실제 좌표를 복구한다.
    return _resolve_reference_point_origin(
        normalized,
        api_key,
    )


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


GENERIC_PLACE_WORDS = {
    "가게",
    "매장",
    "업체",
    "점",
    "수리점",
    "정비소",
    "전문점",
    "센터",
    "서비스센터",
    "곳",
}


def _compact_term_variants(term):
    normalized = " ".join(
        str(term or "").split()
    ).strip()

    if not normalized:
        return []

    tokens = re.findall(
        r"[0-9a-zA-Z가-힣]{2,}",
        normalized,
    )
    meaningful = [
        token
        for token in tokens
        if token not in GENERIC_PLACE_WORDS
    ]

    variants = []

    compact = " ".join(meaningful).strip()
    if compact and compact != normalized:
        variants.append(compact)

    for token in meaningful:
        if token not in variants:
            variants.append(token)

    if normalized not in variants:
        variants.append(normalized)

    # 음식/업종 표현의 구어체 접미사는 공급자 검색에서 넓게 재시도한다.
    # 예: "국밥집" -> "국밥", "타이어전문점" -> "타이어".
    for suffix in ("전문점", "가게", "매장", "집"):
        if normalized.endswith(suffix):
            base = normalized[: -len(suffix)].strip()
            if len(base) >= 2 and base not in variants:
                variants.insert(0, base)

    return variants


BROAD_SEARCH_MODES = {
    "category_discovery",
    "area_discovery",
    "comparison",
}


def _is_broad_search(mission):
    return str(
        mission.get("search_mode") or ""
    ).strip() in BROAD_SEARCH_MODES


def _effective_target_business(mission):
    mode = str(
        mission.get("search_mode") or ""
    ).strip()
    target = str(
        mission.get("target_business") or ""
    ).strip()

    if mode in {
        "category_discovery",
        "area_discovery",
        "comparison",
        "general",
    }:
        return ""

    return target


def _search_queries(mission):
    location = str(
        mission.get("location") or ""
    ).strip()
    target_business = _effective_target_business(
        mission
    )
    location_explicit = (
        mission.get("location_explicit") is True
    )

    # 사용자가 현재 요청에서 새 고유 장소를 직접 지목한 경우
    # 이전 대화의 업종/세부지역이 검색을 오염시키지 않게 한다.
    # 위치를 이번 요청에서 직접 말하지 않았다면 장소명 자체를
    # 첫 검색어로 사용한다.
    if target_business:
        queries = []

        if location_explicit and location:
            queries.append(
                f"{location} {target_business}".strip()
            )

        if target_business not in queries:
            queries.append(target_business)

        if location and not location_explicit:
            # 문맥상 지역은 보조 검색에만 사용한다.
            contextual = (
                f"{location} {target_business}"
            ).strip()
            if contextual not in queries:
                queries.append(contextual)

        return queries[:3]

    raw_terms = mission.get("search_terms")
    search_terms = (
        [
            str(item).strip()
            for item in raw_terms
            if str(item).strip()
        ]
        if isinstance(raw_terms, list)
        else []
    )

    raw_subcategories = mission.get("subcategories")
    subcategories = (
        [
            str(item).strip()
            for item in raw_subcategories
            if str(item).strip()
        ]
        if isinstance(raw_subcategories, list)
        else []
    )

    subject = str(
        mission.get("subject") or ""
    ).strip()
    category = str(
        mission.get("category") or ""
    ).strip()

    primary_terms = []

    if target_business:
        primary_terms.append(target_business)

    for item in [
        *search_terms,
        *subcategories,
    ]:
        for variant in _compact_term_variants(item):
            if variant not in primary_terms:
                primary_terms.append(variant)

    fallback_terms = []

    for item in [
        subject,
        category,
    ]:
        for variant in _compact_term_variants(item):
            if (
                variant
                and variant not in primary_terms
                and variant not in fallback_terms
            ):
                fallback_terms.append(variant)

    if not primary_terms:
        primary_terms = fallback_terms[:1]
        fallback_terms = fallback_terms[1:]

    location_variants = _location_variants(
        location
    )
    queries = []

    # 모든 검색어를 한 지역에서 소모하지 않는다.
    # 가장 구체적인 지역과 그 상위 지역에 대해
    # 가장 짧고 핵심적인 검색어를 먼저 보장한다.
    priority_terms = [
        *primary_terms[:3],
        *fallback_terms[:1],
    ]

    for location_variant in location_variants[:3]:
        for term in priority_terms:
            query = " ".join(
                part
                for part in (
                    location_variant,
                    term,
                )
                if part
            ).strip()

            if query and query not in queries:
                queries.append(query)

            if len(queries) >= 8:
                return queries

    for term in [
        *primary_terms[3:],
        *fallback_terms[1:],
    ]:
        for location_variant in location_variants:
            query = " ".join(
                part
                for part in (
                    location_variant,
                    term,
                )
                if part
            ).strip()

            if query and query not in queries:
                queries.append(query)

            if len(queries) >= 8:
                return queries

    if not queries:
        raise ResearchConfigurationError(
            "실제 업체 검색에 사용할 지역 또는 대상 정보가 부족합니다."
        )

    return queries

RELEVANCE_STOP_WORDS = {
    *GENERIC_PLACE_WORDS,
    "오늘",
    "내일",
    "지금",
    "영업",
    "영업중",
    "가능",
    "추천",
    "가까운",
    "근처",
    "주변",
    "예약",
    "문의",
    "찾아줘",
    "찾기",
}


ADMIN_SUFFIXES = (
    "특별시",
    "광역시",
    "특별자치시",
    "특별자치도",
    "도",
    "시",
    "군",
    "구",
    "읍",
    "면",
    "동",
    "리",
)


def _location_scope_tokens(location):
    tokens = re.findall(
        r"[0-9a-zA-Z가-힣]{2,}",
        str(location or "").strip(),
    )
    admin_tokens = [
        token
        for token in tokens
        if token.endswith(ADMIN_SUFFIXES)
    ]

    # 광역 단위만 너무 강하게 잡으면 검색결과를 불필요하게
    # 버릴 수 있어 시/군/구 이하를 우선한다.
    specific = [
        token
        for token in admin_tokens
        if token.endswith(
            ("시", "군", "구", "읍", "면", "동", "리")
        )
    ]

    return specific or admin_tokens or tokens


def _matches_location(document, location):
    required = _location_scope_tokens(
        location
    )
    if not required:
        return True

    haystack = " ".join(
        [
            str(
                document.get("address_name") or ""
            ),
            str(
                document.get(
                    "road_address_name"
                )
                or ""
            ),
        ]
    ).lower()

    return all(
        token.lower() in haystack
        for token in required
    )


def _matches_target_business(
    document,
    mission,
):
    target = re.sub(
        r"[^0-9a-zA-Z가-힣]",
        "",
        _effective_target_business(
            mission
        ).lower(),
    )
    if not target:
        return True

    place_name = re.sub(
        r"[^0-9a-zA-Z가-힣]",
        "",
        str(
            document.get("place_name")
            or ""
        ).lower(),
    )

    if not place_name:
        return False

    return (
        target in place_name
        or place_name in target
    )


def _mission_keywords(mission):
    raw_subcategories = mission.get("subcategories")
    raw_search_terms = mission.get("search_terms")

    subcategories = (
        [
            str(item).lower().strip()
            for item in raw_subcategories
            if str(item).strip()
        ]
        if isinstance(raw_subcategories, list)
        else []
    )
    search_terms = (
        [
            str(item).lower().strip()
            for item in raw_search_terms
            if str(item).strip()
        ]
        if isinstance(raw_search_terms, list)
        else []
    )

    # 검색 적합성은 사용자가 실제로 찾으려는 업종/서비스 검색어를
    # 우선한다. "임플란트", "야간진료"처럼 세부조건만으로
    # 정상 업체 전체를 탈락시키지 않도록 subcategories는
    # 검색어가 없을 때의 보조 신호로만 사용한다.
    values = list(search_terms or subcategories)
    subject_value = str(
        mission.get("subject") or ""
    ).lower().strip()
    subject_is_strict_food = any(
        term in subject_value
        for term in STRICT_FOOD_KEYWORDS
    )
    if (
        subject_is_strict_food
        and subject_value
        and subject_value not in values
    ):
        values.append(subject_value)
    if not values:
        values = [
            subject_value
            or str(
                mission.get("category") or ""
            ).lower().strip()
        ]

    location_tokens = set(
        re.findall(
            r"[0-9a-zA-Z가-힣]{2,}",
            str(
                mission.get("location") or ""
            ).lower(),
        )
    )
    category_tokens = set(
        re.findall(
            r"[0-9a-zA-Z가-힣]{2,}",
            str(
                mission.get("category") or ""
            ).lower(),
        )
    )

    keywords = []
    for value in values:
        for token in re.findall(
            r"[0-9a-zA-Z가-힣]{2,}",
            value,
        ):
            if (
                token in location_tokens
                or token in RELEVANCE_STOP_WORDS
                or token in keywords
            ):
                continue
            keywords.append(token)
            for suffix in (
                "전문점",
                "가게",
                "매장",
                "집",
            ):
                if token.endswith(suffix):
                    base = token[: -len(suffix)].strip()
                    if (
                        len(base) >= 2
                        and base not in keywords
                    ):
                        keywords.append(base)

    # "자동차 타이어"처럼 넓은 category 단어와
    # 구체 서비스 단어가 같이 들어오면 구체 단어를 우선한다.
    specific_keywords = [
        keyword
        for keyword in keywords
        if keyword not in category_tokens
    ]
    if specific_keywords:
        keywords = specific_keywords

    return keywords[:12]


KAKAO_CATEGORY_GROUP_ALIASES = {
    "식당": {"FD6"},
    "음식점": {"FD6"},
    "맛집": {"FD6"},
    "밥집": {"FD6"},
    "레스토랑": {"FD6"},
    "국밥": {"FD6"},
    "국밥집": {"FD6"},
    "쌈밥": {"FD6"},
    "쌈밥집": {"FD6"},
    "카페": {"CE7"},
    "커피": {"CE7"},
    "병원": {"HP8"},
    "약국": {"PM9"},
    "주차장": {"PK6"},
    "주유소": {"OL7"},
    "은행": {"BK9"},
    "마트": {"MT1"},
    "편의점": {"CS2"},
    "학교": {"SC4"},
    "학원": {"AC5"},
    "지하철역": {"SW8"},
    "부동산": {"AG2"},
    "공공기관": {"PO3"},
    "관광지": {"AT4"},
    "호텔": {"AD5"},
    "숙박": {"AD5"},
}


def _matches_kakao_category_group(
    document,
    keywords,
):
    group_code = str(
        document.get("category_group_code") or ""
    ).strip()

    if not group_code:
        return False

    expected_codes = set()
    for keyword in keywords:
        expected_codes.update(
            KAKAO_CATEGORY_GROUP_ALIASES.get(
                keyword,
                set(),
            )
        )

    return bool(expected_codes) and group_code in expected_codes


def _matches_mission(document, mission):
    target_business = _effective_target_business(
        mission
    )

    # 고유 장소명 검색에서는 과거 대화에서 남아 있을 수 있는
    # 식당/미용실 등의 업종 키워드로 정확한 장소를 탈락시키지 않는다.
    if target_business:
        return _matches_target_business(
            document,
            mission,
        )

    keywords = _mission_keywords(mission)
    if not keywords:
        return True

    haystack = " ".join(
        [
            str(
                document.get("place_name") or ""
            ).lower(),
            str(
                document.get("category_name") or ""
            ).lower(),
        ]
    )

    category_keywords = [
        token
        for token in re.findall(
            r"[0-9a-zA-Z가-힣]{2,}",
            str(
                mission.get("category") or ""
            ).lower(),
        )
        if token
    ]
    specific_keywords = [
        keyword
        for keyword in keywords
        if keyword not in category_keywords
    ]

    group_code = str(
        document.get("category_group_code") or ""
    ).strip()
    category_text = str(
        document.get("category_name") or ""
    ).lower()

    if (
        group_code == "FD6"
        and specific_keywords
        and any(
            marker in category_text
            for marker in INCOMPATIBLE_FOOD_VENUE_MARKERS
        )
    ):
        return False

    strict_food_requested = any(
        keyword in STRICT_FOOD_KEYWORDS
        for keyword in specific_keywords
    )

    if strict_food_requested:
        return any(
            keyword in haystack
            for keyword in specific_keywords
            if keyword in STRICT_FOOD_KEYWORDS
        )

    if specific_keywords and any(
        keyword in haystack
        for keyword in specific_keywords
    ):
        return True

    if specific_keywords:
        if group_code == "FD6":
            return True

        return False

    if _matches_kakao_category_group(
        document,
        keywords,
    ):
        return True

    if _matches_kakao_category_group(
        document,
        category_keywords,
    ):
        return True

    return any(
        keyword in haystack
        for keyword in keywords
    )

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
        "distance_m": str(
            document.get("distance") or ""
        ).strip(),
        "image_url": None,
        "source": "kakao",
    }


def _requested_result_count(mission):
    raw = mission.get("requested_count")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 10

    return max(1, min(value, 10))

def enrich_place_businesses(
    businesses,
    mission,
    *,
    naver_client_id=None,
    naver_client_secret=None,
    openai_api_key=None,
    google_places_api_key=None,
    gpt_direct=False,
):
    """Enrich already verified Kakao candidates without searching again."""
    if not isinstance(businesses, list):
        raise ValueError("업체 목록이 필요합니다.")
    if not isinstance(mission, dict):
        raise ValueError("검색 조건이 필요합니다.")

    safe = [
        dict(item)
        for item in businesses[:10]
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and str(item.get("address") or "").strip()
    ]
    if not safe:
        return []

    safe = merge_businesses_from_graph(safe)

    if gpt_direct:
        raw_criteria = mission.get("criteria")
        criteria = (
            [
                item
                for item in raw_criteria
                if isinstance(item, dict)
            ]
            if isinstance(raw_criteria, list)
            else []
        )
        realtime_fields = {
            str(item.get("field") or "").strip()
            for item in criteria
            if str(item.get("field") or "").strip()
            in {"availability", "stock"}
        }

        def needs_followup_evidence(item):
            if realtime_fields:
                return True
            # A fresh timestamp on an incomplete record must never prevent
            # discovering missing photos, opening hours, product evidence, etc.
            naver = item.get("naver")
            naver = naver if isinstance(naver, dict) else {}
            if (
                not str(item.get("image_url") or "").strip()
                or not naver.get("opening_hours")
                or naver.get("parking_available") is None
                or not naver.get("prices")
            ):
                return True
            if not criteria:
                return False
            matching = match_businesses(mission, [item])
            return matching.get("unverified_count", 0) > 0

        fresh = [
            item
            for item in safe
            if item.get("araba_cache_hit") is True
            and item.get("araba_detail_fresh") is True
            and not needs_followup_evidence(item)
        ]
        stale = [
            item
            for item in safe
            if item not in fresh
        ]
        if not stale:
            runtime = enrich_businesses_with_google_places(
                safe,
                api_key=google_places_api_key,
            )
            runtime = enrich_businesses_with_agents(
                mission,
                runtime,
            )
            runtime = enforce_business_images(
                runtime
            )
            persist_businesses(
                runtime, mission, detail_refreshed=False
            )
            return annotate_businesses_now(
                runtime
            )

        # Refresh from the actual provider identity before considering
        # model-extracted facts. Preserve the original business identity.
        refreshed_kakao = enrich_businesses_with_kakao_pages(
            stale[:FAST_DETAIL_ENRICH_LIMIT]
        )
        refreshed_naver = enrich_businesses_with_naver(
            refreshed_kakao,
            client_id=naver_client_id,
            client_secret=naver_client_secret,
        )
        enriched_stale = enrich_businesses_with_openai_web(
            [*refreshed_naver, *stale[FAST_DETAIL_ENRICH_LIMIT:]],
            mission,
            api_key=openai_api_key,
        )
        persisted_stale = persist_businesses(
            enriched_stale,
            mission,
            detail_refreshed=True,
        )
        refreshed = {
            str(item.get("id") or "").strip()
            or (
                str(item.get("name") or "").strip()
                + "|"
                + str(item.get("address") or "").strip()
            ): item
            for item in persisted_stale
        }
        combined = []
        for item in safe:
            key = (
                str(item.get("id") or "").strip()
                or (
                    str(item.get("name") or "").strip()
                    + "|"
                    + str(item.get("address") or "").strip()
                )
            )
            combined.append(refreshed.get(key, item))
        runtime = enrich_businesses_with_google_places(
            combined,
            api_key=google_places_api_key,
        )
        runtime = enrich_businesses_with_agents(
            mission,
            runtime,
        )
        runtime = enforce_business_images(
            runtime
        )
        # Google facts (hours/phone/source) were previously runtime-only;
        # write verified factual improvements back into the ARABA Graph.
        persist_businesses(
            runtime, mission, detail_refreshed=False
        )
        return annotate_businesses_now(
            runtime
        )

    detail_targets = safe[:FAST_DETAIL_ENRICH_LIMIT]
    deferred_targets = safe[FAST_DETAIL_ENRICH_LIMIT:]

    enriched_primary = enrich_businesses_with_kakao_pages(
        detail_targets
    )
    for item in deferred_targets:
        item["kakao_page_checked"] = False

    kakao_businesses = [
        *enriched_primary,
        *deferred_targets,
    ]
    naver_primary = enrich_businesses_with_naver(
        kakao_businesses[:FAST_DETAIL_ENRICH_LIMIT],
        client_id=naver_client_id,
        client_secret=naver_client_secret,
    )
    deferred_naver = [
        {
            **item,
            "naver": {
                "matched": False,
                "page_checked": False,
                "status": "deferred_fast_response",
            },
        }
        for item in kakao_businesses[FAST_DETAIL_ENRICH_LIMIT:]
    ]
    enriched = [
        *naver_primary,
        *deferred_naver,
    ]
    enriched = enrich_businesses_with_web(
        enriched,
        mission,
        client_id=naver_client_id,
        client_secret=naver_client_secret,
    )
    enriched = enrich_businesses_with_openai_web(
        enriched,
        mission,
        api_key=openai_api_key,
    )
    persisted = persist_businesses(
        enriched,
        mission,
        detail_refreshed=True,
    )
    runtime = enrich_businesses_with_google_places(
        persisted,
        api_key=google_places_api_key,
    )
    runtime = enrich_businesses_with_agents(
        mission,
        runtime,
    )
    runtime = enforce_business_images(
        runtime
    )
    persist_businesses(
        runtime, mission, detail_refreshed=False
    )
    return annotate_businesses_now(
        runtime
    )



def _inside_verified_radius(document, origin, radius_km=3):
    """Never let a national text-search result escape a device search radius."""
    if not origin or origin.get("source") != "device_location":
        return True
    try:
        latitude = float(document["y"])
        longitude = float(document["x"])
        center_lat = float(origin["latitude"])
        center_lon = float(origin["longitude"])
        limit = max(0.1, min(float(radius_km), 20))
    except (KeyError, TypeError, ValueError):
        return False

    d_lat = math.radians(latitude - center_lat)
    d_lon = math.radians(longitude - center_lon)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(center_lat))
        * math.cos(math.radians(latitude))
        * math.sin(d_lon / 2) ** 2
    )
    distance = 6371.0088 * 2 * math.atan2(
        math.sqrt(a), math.sqrt(max(0.0, 1 - a))
    )
    return distance <= limit


def search_real_businesses(
    mission,
    api_key=None,
    *,
    naver_client_id=None,
    naver_client_secret=None,
    openai_api_key=None,
    google_places_api_key=None,
    quick_cards=False,
):
    requested_count = _requested_result_count(
        mission
    )
    cached = cached_businesses_for_mission(
        mission,
        requested_count=requested_count,
    )
    cached_businesses = cached.get("businesses") or []
    if cached.get("complete") is True and cached_businesses:
        # Cache completeness is about *business count*, not fact completeness.
        # Required conditions and missing photo/details must be revisited.
        # Cached records remain the identity source of truth; verified external
        # evidence is merged back into those same records.
        # Cached cards created before source verification may have no image.
        # Retry only identity-unverified Kakao candidates, not broad web images.
        missing_photo_candidates = [
            item for item in cached_businesses[:FAST_DETAIL_ENRICH_LIMIT]
            if not str(item.get("image_url") or "").strip()
            and str(item.get("place_url") or "").startswith(
                "https://place.map.kakao.com/"
            )
            and item.get("kakao_photo_status") != "no_image_in_page"
        ]
        if missing_photo_candidates:
            checked = enrich_businesses_with_kakao_pages(
                missing_photo_candidates
            )
            by_id = {
                str(item.get("id") or ""): item
                for item in checked
            }
            cached_businesses = [
                by_id.get(str(item.get("id") or ""), item)
                for item in cached_businesses
            ]
            persist_businesses(
                checked,
                mission,
                detail_refreshed=False,
            )
        if not quick_cards:
            cached_businesses = enrich_place_businesses(
                cached_businesses,
                mission,
                naver_client_id=naver_client_id,
                naver_client_secret=naver_client_secret,
                openai_api_key=openai_api_key,
                google_places_api_key=google_places_api_key,
                gpt_direct=True,
            )
        else:
            cached_businesses = enrich_businesses_with_google_places(
                cached_businesses,
                api_key=google_places_api_key,
            )
            # Persist newly verified hours, phone and source metadata without
            # treating transient Google photo URLs as durable image files.
            persist_businesses(
                cached_businesses,
                mission,
                detail_refreshed=False,
            )
            cached_businesses = enrich_businesses_with_agents(
                mission,
                cached_businesses,
            )
        cached_businesses = enforce_business_images(
            cached_businesses
        )
        cached_businesses = annotate_businesses_now(
            cached_businesses
        )
        matching = (
            match_businesses(mission, cached_businesses)
            if not quick_cards
            else None
        )
        display_businesses = (
            matching["display_businesses"]
            if isinstance(matching, dict)
            else cached_businesses
        )
        unverified_businesses = (
            matching["unverified_businesses"]
            if isinstance(matching, dict)
            else []
        )
        evaluation = evaluate_research_result(
            mission,
            display_businesses,
            reference_origin=None,
        )
        return {
            "source": "araba_db",
            "detail_status": "cached",
            "primary_source": "araba_db",
            "secondary_source": "stored_sources",
            "fallback_source": "external_refresh_if_stale",
            "search_query": "ARABA Business Graph",
            "search_mode": str(
                mission.get("search_mode") or ""
            ).strip(),
            "businesses": display_businesses,
            "unverified_businesses": unverified_businesses,
            "matching": matching,
            "displayed_count": len(display_businesses),
            "requested_count": requested_count,
            "strict_category_filter": True,
            "kakao_reported_total_count": None,
            "count_is_exhaustive": False,
            "evaluation": evaluation,
            "naver_matched_count": sum(
                1
                for item in display_businesses
                if isinstance(item.get("naver"), dict)
                and item["naver"].get("matched") is True
            ),
            "naver_page_checked_count": sum(
                1
                for item in display_businesses
                if isinstance(item.get("naver"), dict)
                and item["naver"].get("page_checked") is True
            ),
            "detail_enrichment_limit": FAST_DETAIL_ENRICH_LIMIT,
            "detail_deferred_count": 0,
            "business_graph_hit": True,
            "needs_location_clarification": False,
            "reference_origin": None,
            "resolved_location_type": "cached",
            "time_context": current_time_context(),
        }

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
    broad_search = _is_broad_search(
        mission
    )
    collected = {}
    kakao_total_count = None

    target_business = _effective_target_business(
        mission
    )
    location_explicit = (
        mission.get("location_explicit") is True
    )

    location_context = mission.get("location_context")
    if not isinstance(location_context, dict):
        location_context = {}

    location_type = str(
        location_context.get("type") or ""
    ).strip()
    location_value = str(
        location_context.get("value")
        or mission.get("location")
        or ""
    ).strip()

    if location_type == "device_location":
        try:
            device_latitude = float(
                location_context.get("latitude")
            )
            device_longitude = float(
                location_context.get("longitude")
            )
        except (TypeError, ValueError):
            reference_origin = None
        else:
            reference_origin = {
                "label": "현재 위치",
                "latitude": str(device_latitude),
                "longitude": str(device_longitude),
                "source": "device_location",
                "accuracy": "device_location",
            }
    elif location_type == "reference_point":
        reference_origin = (
            _resolve_reference_point_origin(
                location_value,
                resolved_api_key,
            )
        )
    else:
        reference_origin = _resolve_location_origin(
            mission.get("location"),
            resolved_api_key,
            mission=mission,
        )

    if (
        (location_type == "device_location" and reference_origin is None)
        or (
            location_explicit
            and location_value
            and reference_origin is None
        )
    ):
        return {
            "source": "kakao",
            "detail_status": "location_unresolved",
            "search_query": None,
            "search_mode": str(
                mission.get("search_mode") or ""
            ).strip(),
            "businesses": [],
            "matching": None,
            "displayed_count": 0,
            "requested_count": requested_count,
            "strict_category_filter": True,
            "needs_location_clarification": True,
            "unresolved_location": location_value,
            "clarification_question": (
                f'"{location_value}" 위치를 확인하지 못했어요. '
                "정확한 지역이나 기준 장소 이름을 다시 말씀해주세요."
            ),
            "reference_origin": None,
            "resolved_location_type": "unresolved",
        }

    # LLM이 "창원시청 주변"을 행정구역으로 잘못 분류해도,
    # 실제 주소검색 실패 뒤 장소좌표가 확인되면 기준장소 검색으로
    # 자동 승격한다. 검색 성공 여부를 모델 분류 한 번에 맡기지 않는다.
    resolved_location_type = location_type
    if (
        reference_origin
        and reference_origin.get("accuracy")
        in {"place_reference", "device_location"}
    ):
        resolved_location_type = "reference_point"

    search_mission = dict(mission)

    if reference_origin:
        if resolved_location_type == "reference_point":
            # 기준 장소는 행정구역이 아니다. 업체 주소 문자열에
            # 장소명이 포함되는지 검사하지 말고 좌표 기준으로 찾는다.
            search_mission["location"] = ""
        else:
            canonical_location = str(
                reference_origin.get("label") or ""
            ).strip()
            if canonical_location:
                search_mission["location"] = canonical_location

    search_queries = _search_queries(
        search_mission
    )

    # Kakao text search can return zero results for long administrative-area
    # phrases even when the category exists nearby. When the location was
    # resolved to coordinates, try the bare category/service term immediately
    # after the most specific query and keep the strict address filter below.
    # This improves recall without letting out-of-area businesses through.
    if reference_origin:
        raw_terms = mission.get("search_terms")
        coordinate_terms = (
            [
                str(item).strip()
                for item in raw_terms
                if str(item).strip()
            ]
            if isinstance(raw_terms, list)
            else []
        )
        coordinate_fallback = None
        for raw_term in [
            *coordinate_terms,
            str(mission.get("category") or "").strip(),
        ]:
            for term in _compact_term_variants(raw_term):
                if term and term not in search_queries:
                    coordinate_fallback = term
                    break
            if coordinate_fallback:
                break
        if coordinate_fallback:
            search_queries.insert(1, coordinate_fallback)

    for query in search_queries[:MAX_KAKAO_QUERY_ATTEMPTS]:
        try:
            response = httpx.get(
                KAKAO_LOCAL_SEARCH_URL,
                headers={
                    "Authorization": f"KakaoAK {resolved_api_key}",
                },
                params={
                    "query": query,
                    "size": (
                        15
                        if broad_search
                        else 8
                    ),
                    **(
                        {
                            "x": reference_origin["longitude"],
                            "y": reference_origin["latitude"],
                            "sort": "distance",
                            **(
                                {
                                    "radius": int(
                                        max(
                                            100,
                                            min(
                                                float(
                                                    location_context.get(
                                                        "radius_hint_km"
                                                    )
                                                    or 3
                                                )
                                                * 1000,
                                                20000,
                                            ),
                                        )
                                    )
                                }
                                if resolved_location_type
                                == "reference_point"
                                else {}
                            ),
                        }
                        if (
                            reference_origin
                            and (
                                not target_business
                                or location_explicit
                                or resolved_location_type
                                == "reference_point"
                            )
                        )
                        else {}
                    ),
                },
                timeout=httpx.Timeout(
                    3.5,
                    connect=1.5,
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
        meta = payload.get("meta")
        if (
            kakao_total_count is None
            and isinstance(meta, dict)
            and isinstance(
                meta.get("total_count"),
                int,
            )
        ):
            kakao_total_count = meta.get(
                "total_count"
            )

        filtered = []
        if isinstance(raw_documents, list):
            scoped_documents = [
                item
                for item in raw_documents
                if isinstance(item, dict)
                and (
                    True
                    if (
                        target_business
                        and not location_explicit
                    )
                    else (
                        True
                        if resolved_location_type
                        == "reference_point"
                        else _matches_location(
                            item,
                            search_mission.get(
                                "location"
                            ),
                        )
                    )
                )
                and _inside_verified_radius(
                    item,
                    reference_origin,
                    location_context.get("radius_hint_km") or 3,
                )
                and _matches_target_business(
                    item,
                    mission,
                )
            ]

            filtered = [
                item
                for item in scoped_documents
                if _matches_mission(
                    item,
                    mission,
                )
            ]

        if filtered and selected_query is None:
            selected_query = query

        if broad_search:
            for item in filtered:
                key = str(
                    item.get("id")
                    or "|".join(
                        [
                            str(
                                item.get(
                                    "place_name"
                                )
                                or ""
                            ),
                            str(
                                item.get(
                                    "address_name"
                                )
                                or ""
                            ),
                        ]
                    )
                )
                if key and key not in collected:
                    collected[key] = item

            if len(collected) >= requested_count:
                break
        elif filtered:
            documents = filtered
            break

    if broad_search:
        documents = list(
            collected.values()
        )[:requested_count]

    if not documents and last_error is not None:
        raise ResearchProviderError(
            "카카오 장소검색 서버에 연결하지 못했습니다."
        ) from last_error

    kakao_businesses = [
        business
        for business in (
            _normalize_business(item)
            for item in documents
            if isinstance(item, dict)
        )
        if business["name"]
    ]
    kakao_businesses = merge_businesses_from_graph(
        kakao_businesses
    )

    if quick_cards:
        persisted = persist_businesses(
            kakao_businesses,
            mission,
            detail_refreshed=False,
        )
        businesses = enrich_businesses_with_google_places(
            persisted,
            api_key=google_places_api_key,
        )
        businesses = enrich_businesses_with_agents(
            mission,
            businesses,
        )
        businesses = enforce_business_images(
            businesses
        )
        persist_businesses(
            businesses, mission, detail_refreshed=False
        )
        businesses = annotate_businesses_now(
            businesses
        )
    else:
        businesses = enrich_place_businesses(
            kakao_businesses,
            mission,
            naver_client_id=naver_client_id,
            naver_client_secret=naver_client_secret,
            openai_api_key=openai_api_key,
            google_places_api_key=google_places_api_key,
        )

    naver_matched_count = sum(
        1
        for item in businesses
        if isinstance(item.get("naver"), dict)
        and item["naver"].get("matched") is True
    )
    naver_page_checked_count = sum(
        1
        for item in businesses
        if isinstance(item.get("naver"), dict)
        and item["naver"].get("page_checked") is True
    )

    category = str(
        mission.get("category") or "기타"
    ).strip()

    matching = (
        match_businesses(
            mission,
            businesses,
        )
        if not quick_cards
        else None
    )
    display_businesses = (
        matching["display_businesses"]
        if isinstance(matching, dict)
        else businesses
    )
    unverified_businesses = (
        matching["unverified_businesses"]
        if isinstance(matching, dict)
        else []
    )

    evaluation = evaluate_research_result(
        mission,
        display_businesses,
        reference_origin=reference_origin,
    )

    return {
        "source": (
            "araba_db+kakao"
            if any(
                item.get("araba_cache_hit") is True
                for item in businesses
            )
            else (
                "kakao"
                if quick_cards
                else "kakao+naver"
            )
        ),
        "detail_status": "pending" if quick_cards else "complete",
        "primary_source": "kakao",
        "secondary_source": "naver_place",
        "fallback_source": "naver_blog+web",
        "search_query": selected_query,
        "search_mode": str(
            mission.get("search_mode")
            or ""
        ).strip(),
        "businesses": display_businesses,
        "unverified_businesses": unverified_businesses,
        "matching": matching,
        "displayed_count": len(display_businesses),
        "requested_count": requested_count,
        "strict_category_filter": True,
        "kakao_reported_total_count": kakao_total_count,
        "count_is_exhaustive": False,
        "evaluation": evaluation,
        "naver_matched_count": naver_matched_count,
        "naver_page_checked_count": naver_page_checked_count,
        "detail_enrichment_limit": FAST_DETAIL_ENRICH_LIMIT,
        "detail_deferred_count": max(
            0,
            len(businesses) - FAST_DETAIL_ENRICH_LIMIT,
        ),
        "kakao_photo_count": sum(
            1
            for item in businesses
            if str(
                item.get("image_url") or ""
            ).strip()
            and item.get("image_source")
            == "kakao_place"
        ),
        "kakao_photo_status_counts": {
            status: sum(
                1
                for item in businesses
                if item.get("kakao_photo_status") == status
            )
            for status in (
                "found",
                "no_image_in_page",
                "page_fetch_failed",
                "page_unavailable",
                "page_error",
                "not_kakao_place_url",
            )
        },
        "web_enriched_count": sum(
            1
            for item in businesses
            if isinstance(item.get("web"), dict)
            and item["web"].get("status")
            == "matched"
        ),
        "openai_web_enriched_count": sum(
            1
            for item in businesses
            if isinstance(
                item.get("openai_web"),
                dict,
            )
            and item["openai_web"].get(
                "matched"
            )
            is True
        ),
        "openai_web_status_counts": {
            status_name: sum(
                1
                for item in businesses
                if isinstance(
                    item.get("openai_web"),
                    dict,
                )
                and item["openai_web"].get(
                    "status"
                )
                == status_name
            )
            for status_name in (
                "matched",
                "provider_error",
                "identity_not_confirmed",
                "not_returned",
                "no_detail_found",
                "not_configured",
                "not_needed",
                "deferred_fast_response",
                "enrichment_error",
            )
        },
        "representative_photo_count": sum(
            1
            for item in businesses
            if str(
                item.get("image_url") or ""
            ).strip()
        ),
        "opening_hours_count": sum(
            1
            for item in businesses
            if isinstance(item.get("naver"), dict)
            and isinstance(item["naver"].get("opening_hours"), list)
            and bool(item["naver"].get("opening_hours"))
        ),
        "parking_info_count": sum(
            1
            for item in businesses
            if isinstance(item.get("naver"), dict)
            and isinstance(item["naver"].get("parking_available"), bool)
        ),
        "price_info_count": sum(
            1
            for item in businesses
            if isinstance(item.get("naver"), dict)
            and isinstance(item["naver"].get("prices"), list)
            and bool(item["naver"].get("prices"))
        ),
        "reference_origin": reference_origin,
        "resolved_location_type": (
            resolved_location_type
            or "none"
        ),
        "life_info": _life_info_for(category),
        "phone_call_mock": True,
        "final_question": (
            "실제 통화 기능이 연결되면 이 업체에 예약을 진행할까요?"
        ),
        "actions": ["예약하기", "다른 후보 보기", "여기까지"],
        "time_context": current_time_context(),
    }

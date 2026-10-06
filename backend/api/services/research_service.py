import os
import re

import httpx

from .kakao_place_service import enrich_businesses_with_kakao_pages
from .naver_place_service import enrich_businesses_with_naver
from .research_evaluation_service import (
    evaluate_research_result,
)


KAKAO_LOCAL_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/keyword.json"
)
KAKAO_ADDRESS_SEARCH_URL = (
    "https://dapi.kakao.com/v2/local/search/address.json"
)

# 첫 응답을 상세검증 전체에 묶어두면 모바일 조회 타임아웃이 발생할 수 있다.
# 상위 후보만 빠르게 상세검증하고 나머지는 후보 자체를 먼저 반환한다.
FAST_DETAIL_ENRICH_LIMIT = 4


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
    values = search_terms or subcategories
    if not values:
        values = [
            str(
                mission.get("subject") or ""
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

    # 지역명만 같은 아파트·학교·공원 등이 섞이지 않도록
    # 사용자가 요청한 실제 업종/서비스 핵심어가
    # 상호 또는 카카오 업종분류에 반드시 포함돼야 한다.
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
        "image_url": None,
        "source": "kakao",
    }


def search_real_businesses(
    mission,
    api_key=None,
    *,
    naver_client_id=None,
    naver_client_secret=None,
):
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

    if location_type == "reference_point":
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
        )

    search_mission = dict(mission)

    if reference_origin:
        if location_type == "reference_point":
            # 기준 장소는 행정구역이 아니다. 업체 주소 문자열에
            # 장소명이 포함되는지 검사하지 말고 좌표 기준으로 찾는다.
            search_mission["location"] = ""
        else:
            canonical_location = str(
                reference_origin.get("label") or ""
            ).strip()
            if canonical_location:
                search_mission["location"] = canonical_location

    for query in _search_queries(search_mission)[:5]:
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
                                if location_type
                                == "reference_point"
                                else {}
                            ),
                        }
                        if (
                            reference_origin
                            and (
                                not target_business
                                or location_explicit
                                or location_type
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
            filtered = [
                item
                for item in raw_documents
                if isinstance(item, dict)
                and _matches_mission(
                    item,
                    mission,
                )
                and (
                    True
                    if (
                        target_business
                        and not location_explicit
                    )
                    else (
                        True
                        if location_type
                        == "reference_point"
                        else _matches_location(
                            item,
                            search_mission.get(
                                "location"
                            ),
                        )
                    )
                )
                and _matches_target_business(
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

            if len(collected) >= 12:
                break
        elif filtered:
            documents = filtered
            break

    if broad_search:
        documents = list(
            collected.values()
        )[:12]

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

    detail_targets = kakao_businesses[
        :FAST_DETAIL_ENRICH_LIMIT
    ]
    deferred_targets = kakao_businesses[
        FAST_DETAIL_ENRICH_LIMIT:
    ]

    enriched_primary = (
        enrich_businesses_with_kakao_pages(
            detail_targets
        )
    )

    for item in deferred_targets:
        item["kakao_page_checked"] = False

    kakao_businesses = [
        *enriched_primary,
        *deferred_targets,
    ]

    naver_primary = enrich_businesses_with_naver(
        kakao_businesses[
            :FAST_DETAIL_ENRICH_LIMIT
        ],
        client_id=naver_client_id,
        client_secret=naver_client_secret,
    )

    deferred_naver = []
    for item in kakao_businesses[
        FAST_DETAIL_ENRICH_LIMIT:
    ]:
        deferred_naver.append(
            {
                **item,
                "naver": {
                    "matched": False,
                    "page_checked": False,
                    "status": "deferred_fast_response",
                },
            }
        )

    businesses = [
        *naver_primary,
        *deferred_naver,
    ]

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

    evaluation = evaluate_research_result(
        mission,
        businesses,
        reference_origin=reference_origin,
    )

    return {
        "source": "kakao+naver",
        "primary_source": "kakao",
        "secondary_source": "naver_place",
        "search_query": selected_query,
        "search_mode": str(
            mission.get("search_mode")
            or ""
        ).strip(),
        "businesses": businesses,
        "displayed_count": len(businesses),
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
        "reference_origin": reference_origin,
        "life_info": _life_info_for(category),
        "phone_call_mock": True,
        "final_question": (
            "실제 통화 기능이 연결되면 이 업체에 예약을 진행할까요?"
        ),
        "actions": ["예약하기", "다른 후보 보기", "여기까지"],
    }

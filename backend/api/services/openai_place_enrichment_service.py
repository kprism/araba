import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from openai import OpenAI


WEB_ENRICH_MODEL = (
    os.getenv(
        "ARABA_WEB_ENRICH_MODEL",
        "gpt-6-luna",
    ).strip()
    or "gpt-6-luna"
)
WEB_ENRICH_TIMEOUT_SECONDS = 37.0
WEB_ENRICH_LIMIT = 5


# Responses Structured Outputs: every returned fact has a stable field.
# The schema guarantees structure, not truth. Verify identity and sources below.
PLACE_DETAILS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "businesses": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "business_name": {"type": "string"},
                    "identity_match": {"type": "boolean"},
                    "opening_hours": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "parking_available": {
                        "type": ["boolean", "null"],
                    },
                    "parking_text": {
                        "type": ["string", "null"],
                    },
                    "prices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": ["string", "null"]},
                                "price": {"type": "string"},
                                "currency": {"type": "string"},
                            },
                            "required": ["name", "price", "currency"],
                        },
                    },
                    "phone": {"type": ["string", "null"]},
                    "address": {"type": ["string", "null"]},
                    "price_link": {"type": ["string", "null"]},
                    "source_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "index",
                    "business_name",
                    "identity_match",
                    "opening_hours",
                    "parking_available",
                    "parking_text",
                    "prices",
                    "phone",
                    "address",
                    "price_link",
                    "source_urls",
                ],
            },
        }
    },
    "required": ["businesses"],
}


def _clean_text(value):
    text = str(value or "").strip()
    return text or None


def _clean_list(value):
    if not isinstance(value, list):
        return []

    result = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)

    return result


def _safe_url(value):
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = urlparse(text)
    except ValueError:
        return None

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
    ):
        return None

    return text


def _normalize(value):
    return re.sub(
        r"[^0-9a-zA-Z가-힣]",
        "",
        str(value or "").lower(),
    )


def _missing_fields(business):
    naver = business.get("naver")
    naver = (
        dict(naver)
        if isinstance(naver, dict)
        else {}
    )

    missing = []

    if not naver.get("opening_hours"):
        missing.append("영업시간")

    if naver.get("parking_available") is None:
        missing.append("주차")

    if not naver.get("prices"):
        missing.append("가격")

    if not str(
        business.get("image_url") or ""
    ).strip():
        missing.append("대표사진")

    if not str(
        business.get("phone") or ""
    ).strip():
        missing.append("전화번호")

    return missing


def _parse_json(raw):
    text = str(raw or "").strip()
    fence = chr(96) * 3

    if text.startswith(fence):
        text = (
            text.removeprefix(fence + "json")
            .removeprefix(fence)
            .removesuffix(fence)
            .strip()
        )

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start < 0 or end <= start:
            return {}

        try:
            value = json.loads(
                text[start : end + 1]
            )
        except json.JSONDecodeError:
            return {}

    return value if isinstance(value, dict) else {}


def _response_dump(response):
    try:
        return response.model_dump()
    except Exception:
        return {}


def _walk_results(value, found):
    if isinstance(value, dict):
        value_type = str(
            value.get("type") or ""
        ).strip()

        if value_type in {
            "image_result",
            "search_result",
        }:
            found.append(dict(value))

        annotations = value.get("annotations")
        if isinstance(annotations, list):
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue

                url = _safe_url(
                    annotation.get("url")
                )
                if url:
                    found.append(
                        {
                            "type": "citation",
                            "url": url,
                            "title": annotation.get(
                                "title"
                            ),
                        }
                    )

        for child in value.values():
            _walk_results(child, found)

    elif isinstance(value, list):
        for child in value:
            _walk_results(child, found)


def _search_results(response):
    found = []
    _walk_results(
        _response_dump(response),
        found,
    )
    return found


def _source_urls(parsed, raw_results):
    urls = []
    raw_sources = parsed.get("source_urls")
    if isinstance(raw_sources, list):
        for raw in raw_sources:
            url = _safe_url(raw)
            if url and url not in urls:
                urls.append(url)
    return urls[:8]


def _image_candidate(
    business,
    raw_results,
):
    name = _normalize(
        business.get("name")
    )
    category = _normalize(
        business.get("description")
        or business.get("category")
    )
    tokens = [
        _normalize(token)
        for token in re.findall(
            r"[0-9A-Za-z가-힣]{2,}",
            str(
                business.get("name")
                or ""
            ),
        )
    ]

    ranked = []

    for item in raw_results:
        if item.get("type") != "image_result":
            continue

        image_url = _safe_url(
            item.get("image_url")
            or item.get("thumbnail_url")
        )

        if not image_url:
            continue

        caption = " ".join(
            str(item.get(key) or "")
            for key in (
                "caption",
                "title",
                "source_website_url",
            )
        )
        compact = _normalize(caption)
        score = 0

        # Category-only matches can attach a different clinic's photo.
        # Require the actual business name in the result caption.
        if not name or name not in compact:
            continue
        score += 100

        score += sum(
            8
            for token in tokens
            if token and token in compact
        )

        if category and category in compact:
            score += 4

        if score > 0:
            ranked.append(
                (
                    score,
                    image_url,
                    _safe_url(
                        item.get(
                            "source_website_url"
                        )
                    ),
                    _clean_text(
                        item.get("caption")
                    ),
                )
            )

    if not ranked:
        return None

    ranked.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    _, image_url, source_url, caption = ranked[0]

    return {
        "image_url": image_url,
        "source_url": source_url,
        "caption": caption,
    }


def _clean_prices(value):
    if not isinstance(value, list):
        return []

    prices = []

    for item in value:
        if not isinstance(item, dict):
            continue

        price = _clean_text(
            item.get("price")
        )

        if not price:
            continue

        prices.append(
            {
                "name": _clean_text(
                    item.get("name")
                ),
                "price": price,
                "currency": (
                    _clean_text(
                        item.get("currency")
                    )
                    or "KRW"
                ),
            }
        )

        if len(prices) >= 8:
            break

    return prices


def _web_user_location(mission):
    location = str(
        mission.get("location") or ""
    ).strip()

    value = {
        "type": "approximate",
        "country": "KR",
    }

    city_match = re.search(
        r"([가-힣]{2,}(?:특별시|광역시|시))",
        location,
    )
    if city_match:
        value["city"] = city_match.group(1)
    elif location.startswith("서울"):
        value["city"] = "서울"
    elif location.startswith("부산"):
        value["city"] = "부산"

    region_match = re.search(
        r"([가-힣]{2,}(?:특별자치도|도))",
        location,
    )
    if region_match:
        value["region"] = region_match.group(1)

    return value


def _build_batch_prompt(
    businesses,
    mission,
):
    payload = []

    for index, business in enumerate(
        businesses
    ):
        payload.append(
            {
                "index": index,
                "business_name": str(
                    business.get("name")
                    or ""
                ).strip(),
                "address": str(
                    business.get("address")
                    or ""
                ).strip(),
                "category": str(
                    business.get("category")
                    or business.get(
                        "description"
                    )
                    or ""
                ).strip(),
                "missing": _missing_fields(
                    business
                ),
            }
        )

    constraints = mission.get(
        "constraints"
    )
    constraints = (
        [
            str(item).strip()
            for item in constraints
            if str(item).strip()
        ]
        if isinstance(constraints, list)
        else []
    )

    return (
        "한국의 실제 업체 여러 곳을 웹에서 확인한다.\n\n"
        "각 업체마다 업체명과 주소/지역이 같은 곳인지 먼저 검증한다.\n"
        "반드시 각 업체마다 정확한 상호명과 지역/주소를 함께 넣어 웹검색을 수행한다. "
        "필요 정보가 첫 검색에서 확인되지 않으면 영업시간·주차·가격·사진 키워드를 붙여 추가 검색한다.\n"
        "입력된 모든 업체를 각각 확인하고 일부만 조사한 뒤 끝내지 않는다.\n"
        "동명이거나 다른 지역이면 identity_match=false로 표시한다.\n"
        "공식 홈페이지, 네이버/카카오 장소정보, 업체가 직접 등록한 페이지를 우선하고, "
        "그 다음 신뢰할 수 있는 웹페이지와 블로그를 참고한다.\n"
        "현재 웹에서 명시적으로 확인한 값만 사용하고 추측하지 않는다.\n"
        "가격은 항목명과 금액이 함께 확인된 경우만 넣는다.\n"
        "주차는 가능/불가가 명시된 경우만 boolean으로 넣고 불명확하면 null이다.\n"
        "영업시간은 출처에 적힌 문자열을 짧게 정리한다.\n"
        "대표사진은 JSON에 만들지 말고 검색 결과의 이미지 결과를 사용한다.\n"
        f"추가 조건: {', '.join(constraints) if constraints else '없음'}\n\n"
        "확인 대상:\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
        )
        + "\n\n"
        "아래 JSON 객체 하나만 출력한다.\n"
        "{\n"
        '  "businesses": [\n'
        "    {\n"
        '      "index": 0,\n'
        '      "business_name": "업체명",\n'
        '      "identity_match": true,\n'
        '      "opening_hours": [],\n'
        '      "parking_available": null,\n'
        '      "parking_text": null,\n'
        '      "prices": [],\n'
        '      "phone": null,\n'
        '      "address": null,\n'
        '      "price_link": null,\n'
        '      "source_urls": []\n'
        "    }\n"
        "  ]\n"
        "}"
    )


def _apply_one_result(
    business,
    parsed,
    raw_results,
):
    item = dict(business)
    expected_name = _normalize(
        item.get("name")
    )
    returned_name = _normalize(
        parsed.get("business_name")
    )

    identity_match = (
        parsed.get("identity_match") is True
        and bool(returned_name)
        and returned_name == expected_name
    )

    sources = _source_urls(
        parsed,
        raw_results,
    )

    # Do not copy model-suggested facts with no traceable source at all.
    # The URL is retained on the card for user verification.
    if identity_match and not sources:
        item["openai_web"] = {
            "status": "missing_sources",
            "matched": False,
            "sources": [],
        }
        return item

    if not identity_match:
        item["openai_web"] = {
            "status":
                "identity_not_confirmed",
            "matched": False,
            "sources": sources,
        }
        return item

    naver = item.get("naver")
    naver = (
        dict(naver)
        if isinstance(naver, dict)
        else {}
    )

    opening_hours = _clean_list(
        parsed.get("opening_hours")
    )

    if (
        not naver.get("opening_hours")
        and opening_hours
    ):
        naver["opening_hours"] = (
            opening_hours[:14]
        )
        naver["opening_hours_source"] = (
            "openai_web"
        )

    parking_available = parsed.get(
        "parking_available"
    )

    if (
        naver.get("parking_available")
        is None
        and isinstance(
            parking_available,
            bool,
        )
    ):
        naver["parking_available"] = (
            parking_available
        )
        naver["parking_text"] = (
            _clean_text(
                parsed.get("parking_text")
            )
            or (
                "주차 가능"
                if parking_available
                else "주차 불가"
            )
        )
        naver["parking_source"] = (
            "openai_web"
        )

    prices = _clean_prices(
        parsed.get("prices")
    )

    if (
        not naver.get("prices")
        and prices
    ):
        naver["prices"] = prices
        naver["prices_source"] = (
            "openai_web"
        )

    price_link = _safe_url(
        parsed.get("price_link")
    )

    if (
        price_link
        and not naver.get("price_link")
    ):
        naver["price_link"] = (
            price_link
        )

    phone = _clean_text(
        parsed.get("phone")
    )

    if (
        not str(
            item.get("phone") or ""
        ).strip()
        and phone
    ):
        item["phone"] = phone

    image = _image_candidate(
        item,
        raw_results,
    )

    if (
        not str(
            item.get("image_url") or ""
        ).strip()
        and image
    ):
        item["image_url"] = (
            image["image_url"]
        )
        item["image_source"] = (
            "openai_web"
        )
        item["image_source_url"] = (
            image.get("source_url")
        )
        item["image_caption"] = (
            image.get("caption")
        )

    item["naver"] = naver

    detail_found = (
        bool(opening_hours)
        or isinstance(
            parking_available,
            bool,
        )
        or bool(prices)
        or bool(phone)
        or bool(image)
    )

    item["openai_web"] = {
        "status": (
            "matched"
            if detail_found
            else "no_detail_found"
        ),
        "matched": detail_found,
        "identity_confirmed": True,
        "sources": sources,
        "opening_hours_found": bool(opening_hours),
        "parking_found": isinstance(parking_available, bool),
        "prices_found": bool(prices),
        "phone_found": bool(phone),
        "image_found": bool(image),
    }

    return item


def _empty_status(item, status, *, error_type=None, http_status=None):
    result = dict(item)
    diag = {
        "status": status,
        "matched": False,
        "sources": [],
    }
    if error_type:
        diag["error_type"] = error_type
    if isinstance(http_status, int):
        diag["upstream_http_status"] = http_status
    result["openai_web"] = diag
    return result


def _enrich_batch(batch, mission, key):
    """One forced web-search call per 1-2 businesses, no Kakao dependency."""
    client = OpenAI(
        api_key=key,
        timeout=WEB_ENRICH_TIMEOUT_SECONDS,
        max_retries=0,
    )

    try:
        response = client.responses.create(
            model=WEB_ENRICH_MODEL,
            reasoning={"effort": "low"},
            tool_choice="required",
            tools=[
                {
                    "type": "web_search",
                    "search_context_size": "medium",
                    "external_web_access": True,
                    "user_location": _web_user_location(mission),
                    "search_content_types": ["text", "image"],
                    "image_settings": {
                        "max_results": 5,
                        "caption": True,
                    },
                }
            ],
            include=["web_search_call.results"],
            input=_build_batch_prompt(batch, mission),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "araba_place_details",
                    "strict": True,
                    "schema": PLACE_DETAILS_SCHEMA,
                },
            },
            max_output_tokens=1700,
        )
    except Exception as exc:
        # No raw provider response, prompts, URLs, or credentials in diagnostics.
        return [
            _empty_status(
                item,
                "provider_error",
                error_type=type(exc).__name__,
                http_status=getattr(exc, "status_code", None),
            )
            for item in batch
        ]

    parsed = _parse_json(getattr(response, "output_text", ""))
    raw_results = _search_results(response)
    response_dump = _response_dump(response)
    web_called = any(
        entry.get("type") == "web_search_call"
        for entry in response_dump.get("output", [])
        if isinstance(entry, dict)
    )

    if not web_called:
        return [
            _empty_status(item, "web_search_not_run")
            for item in batch
        ]

    raw_items = parsed.get("businesses", [])
    if not isinstance(raw_items, list):
        raw_items = []

    returned = {}
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("index"))
        except (ValueError, TypeError):
            continue
        if 0 <= index < len(batch):
            returned[index] = row

    results = []
    for index, item in enumerate(batch):
        row = returned.get(index)
        if row is None:
            results.append(_empty_status(item, "not_returned"))
        else:
            results.append(_apply_one_result(item, row, raw_results))
    return results


def enrich_businesses_with_openai_web(
    businesses,
    mission,
    *,
    api_key=None,
):
    if not isinstance(businesses, list):
        return []

    safe = [
        dict(item)
        for item in businesses
        if isinstance(item, dict)
    ]
    key = str(api_key or "").strip()
    if not safe:
        return []
    if not key:
        return [
            _empty_status(item, "not_configured")
            for item in safe
        ]

    primary = safe[:WEB_ENRICH_LIMIT]
    deferred = safe[WEB_ENRICH_LIMIT:]
    results = [None] * len(primary)
    batches = []

    for offset in range(0, len(primary), 2):
        group = primary[offset:offset + 2]
        if not any(_missing_fields(item) for item in group):
            results[offset:offset + len(group)] = [
                _empty_status(item, "not_needed")
                for item in group
            ]
        else:
            batches.append((offset, group))

    if batches:
        with ThreadPoolExecutor(
            max_workers=min(3, len(batches))
        ) as executor:
            futures = {
                executor.submit(
                    _enrich_batch,
                    group,
                    mission,
                    key,
                ): (offset, group)
                for offset, group in batches
            }
            for future in as_completed(futures):
                offset, group = futures[future]
                try:
                    values = future.result()
                except Exception as exc:
                    values = [
                        _empty_status(
                            item,
                            "provider_error",
                            error_type=type(exc).__name__,
                        )
                        for item in group
                    ]
                results[offset:offset + len(group)] = values

    return [
        item
        for item in results
        if isinstance(item, dict)
    ] + [
        _empty_status(item, "deferred_fast_response")
        for item in deferred
    ]

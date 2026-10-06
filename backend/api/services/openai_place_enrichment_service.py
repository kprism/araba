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
WEB_ENRICH_TIMEOUT_SECONDS = 10.0
WEB_ENRICH_LIMIT = 5


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

    raw_sources = parsed.get(
        "source_urls"
    )

    if isinstance(raw_sources, list):
        for raw in raw_sources:
            url = _safe_url(raw)
            if url and url not in urls:
                urls.append(url)

    for item in raw_results:
        for key in (
            "url",
            "source_website_url",
        ):
            url = _safe_url(
                item.get(key)
            )
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

        if name and name in compact:
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


def _build_prompt(
    business,
    mission,
    missing,
):
    name = str(
        business.get("name") or ""
    ).strip()
    address = str(
        business.get("address") or ""
    ).strip()
    category = str(
        business.get("category")
        or business.get("description")
        or ""
    ).strip()

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

    return f"""
한국의 실제 업체 한 곳을 웹에서 확인한다.

업체명: {name}
주소: {address}
업종: {category}
확인할 정보: {", ".join(missing)}
추가 조건: {", ".join(constraints) if constraints else "없음"}

반드시 업체명과 지역/주소가 같은 업체인지 먼저 검증하라.
동명이거나 다른 지역이면 identity_match=false로 반환하라.
공식 홈페이지, 네이버/카카오 장소정보, 업체가 직접 등록한 페이지를 우선하고,
그 다음 신뢰할 수 있는 웹페이지와 블로그를 참고하라.
현재 웹에서 명시적으로 확인한 값만 사용하고 추측하지 마라.
가격은 항목명과 금액이 함께 확인된 경우만 넣어라.
주차는 가능/불가가 명시된 경우만 boolean으로 넣고 불명확하면 null이다.
영업시간은 출처에 적힌 문자열을 짧게 정리한다.
대표사진은 JSON에 만들지 말고 검색 결과의 이미지 결과를 사용한다.

아래 JSON 객체 하나만 출력한다.
{{
  "business_name": "{name}",
  "identity_match": true,
  "opening_hours": [],
  "parking_available": null,
  "parking_text": null,
  "prices": [],
  "phone": null,
  "address": null,
  "price_link": null,
  "source_urls": []
}}
""".strip()


def _enrich_one(
    business,
    mission,
    *,
    api_key,
):
    item = dict(business)
    missing = _missing_fields(
        item
    )

    if not missing:
        item["openai_web"] = {
            "status": "not_needed",
            "matched": False,
            "sources": [],
        }
        return item

    client = OpenAI(
        api_key=api_key,
        timeout=WEB_ENRICH_TIMEOUT_SECONDS,
        max_retries=0,
    )

    try:
        response = client.responses.create(
            model=WEB_ENRICH_MODEL,
            tools=[
                {
                    "type": "web_search",
                    "search_context_size": "low",
                    "search_content_types": [
                        "image",
                        "text",
                    ],
                    "image_settings": {
                        "max_results": 3,
                        "caption": True,
                    },
                }
            ],
            include=[
                "web_search_call.results"
            ],
            input=_build_prompt(
                item,
                mission,
                missing,
            ),
            max_output_tokens=900,
        )
    except Exception:
        item["openai_web"] = {
            "status": "provider_error",
            "matched": False,
            "sources": [],
        }
        return item

    parsed = _parse_json(
        response.output_text
    )
    raw_results = _search_results(
        response
    )

    expected_name = _normalize(
        item.get("name")
    )
    returned_name = _normalize(
        parsed.get("business_name")
    )

    identity_match = (
        parsed.get("identity_match") is True
        and (
            not returned_name
            or returned_name == expected_name
            or returned_name in expected_name
            or expected_name in returned_name
        )
    )

    sources = _source_urls(
        parsed,
        raw_results,
    )

    if not identity_match:
        item["openai_web"] = {
            "status": "identity_not_confirmed",
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
    item["openai_web"] = {
        "status": "matched",
        "matched": True,
        "sources": sources,
        "missing_requested": missing,
        "opening_hours_found": bool(
            opening_hours
        ),
        "parking_found": isinstance(
            parking_available,
            bool,
        ),
        "prices_found": bool(prices),
        "image_found": bool(image),
    }

    return item


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

    if not safe or not key:
        return [
            {
                **item,
                "openai_web": {
                    "status": (
                        "not_configured"
                        if not key
                        else "not_needed"
                    ),
                    "matched": False,
                    "sources": [],
                },
            }
            for item in safe
        ]

    primary = safe[
        :WEB_ENRICH_LIMIT
    ]
    deferred = safe[
        WEB_ENRICH_LIMIT:
    ]
    results = [None] * len(primary)

    with ThreadPoolExecutor(
        max_workers=min(
            WEB_ENRICH_LIMIT,
            len(primary),
        )
    ) as executor:
        future_to_index = {
            executor.submit(
                _enrich_one,
                item,
                mission,
                api_key=key,
            ): index
            for index, item in enumerate(
                primary
            )
        }

        for future in as_completed(
            future_to_index
        ):
            index = future_to_index[
                future
            ]

            try:
                results[index] = (
                    future.result()
                )
            except Exception:
                results[index] = {
                    **primary[index],
                    "openai_web": {
                        "status":
                            "enrichment_error",
                        "matched": False,
                        "sources": [],
                    },
                }

    return [
        *[
            item
            for item in results
            if isinstance(item, dict)
        ],
        *[
            {
                **item,
                "openai_web": {
                    "status":
                        "deferred_fast_response",
                    "matched": False,
                    "sources": [],
                },
            }
            for item in deferred
        ],
    ]

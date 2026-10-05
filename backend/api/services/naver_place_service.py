import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx


NAVER_LOCAL_SEARCH_URL = (
    "https://openapi.naver.com/v1/search/local.json"
)

NAVER_ALLOWED_HOST_SUFFIXES = (
    ".naver.com",
    "naver.com",
    "naver.me",
)

NAVER_IMAGE_HOST_SUFFIXES = (
    "pstatic.net",
    "naver.net",
    "navercorp.com",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Mobile Safari/537.36"
)


class NaverPlaceConfigurationError(ValueError):
    pass


class NaverPlaceProviderError(RuntimeError):
    pass


def _env(name):
    return str(os.getenv(name, "")).strip()


def _strip_tags(value):
    text = re.sub(
        r"<[^>]+>",
        "",
        str(value or ""),
    )
    return html.unescape(text).strip()


def _normalize_text(value):
    return re.sub(
        r"[^0-9a-zA-Z가-힣]",
        "",
        _strip_tags(value).lower(),
    )


def _address_tokens(value):
    return {
        token
        for token in re.findall(
            r"[0-9a-zA-Z가-힣]{2,}",
            str(value or "").lower(),
        )
        if token
    }


def _resolve_credentials(
    client_id=None,
    client_secret=None,
):
    resolved_id = str(client_id or "").strip()
    resolved_secret = str(client_secret or "").strip()

    if not resolved_id:
        resolved_id = _env("NAVER_CLIENT_ID")
    if not resolved_secret:
        resolved_secret = _env("NAVER_CLIENT_SECRET")

    if not resolved_id or not resolved_secret:
        raise NaverPlaceConfigurationError(
            "Naver Search API Client ID와 Client Secret이 필요합니다."
        )

    return resolved_id, resolved_secret


def _is_allowed_naver_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and any(
        host == suffix or host.endswith(suffix)
        for suffix in NAVER_ALLOWED_HOST_SUFFIXES
    )


def _is_allowed_naver_image_url(value):
    try:
        parsed = urlparse(
            str(value or "").strip()
        )
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme in ("http", "https")
        and any(
            host == suffix
            or host.endswith("." + suffix)
            for suffix in NAVER_IMAGE_HOST_SUFFIXES
        )
    )


def _match_score(kakao_business, naver_item):
    kakao_name = _normalize_text(
        kakao_business.get("name")
    )
    naver_name = _normalize_text(
        naver_item.get("title")
    )

    if not kakao_name or not naver_name:
        return -1

    score = 0

    if kakao_name == naver_name:
        score += 100
    elif (
        kakao_name in naver_name
        or naver_name in kakao_name
    ):
        score += 65
    else:
        kakao_chunks = set(
            re.findall(
                r"[0-9a-zA-Z가-힣]{2,}",
                str(
                    kakao_business.get("name") or ""
                ).lower(),
            )
        )
        naver_chunks = set(
            re.findall(
                r"[0-9a-zA-Z가-힣]{2,}",
                _strip_tags(
                    naver_item.get("title")
                ).lower(),
            )
        )
        score += len(
            kakao_chunks & naver_chunks
        ) * 14

    kakao_address = (
        kakao_business.get("road_address")
        or kakao_business.get("address")
        or ""
    )
    naver_address = (
        naver_item.get("roadAddress")
        or naver_item.get("address")
        or ""
    )
    overlap = (
        _address_tokens(kakao_address)
        & _address_tokens(naver_address)
    )
    score += min(len(overlap), 6) * 6

    kakao_category = _normalize_text(
        kakao_business.get("category")
    )
    naver_category = _normalize_text(
        naver_item.get("category")
    )
    if (
        kakao_category
        and naver_category
        and (
            kakao_category in naver_category
            or naver_category in kakao_category
        )
    ):
        score += 15

    return score


class _MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts = []
        self.in_title = False
        self.meta = {}
        self.json_ld = []
        self._script_type = None
        self._script_parts = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        lower = tag.lower()

        if lower == "title":
            self.in_title = True
        elif lower == "meta":
            key = (
                attr.get("property")
                or attr.get("name")
                or ""
            ).strip().lower()
            value = str(
                attr.get("content") or ""
            ).strip()
            if key and value:
                self.meta[key] = value
        elif lower == "script":
            script_type = str(
                attr.get("type") or ""
            ).strip().lower()
            self._script_type = script_type
            self._script_parts = []

    def handle_endtag(self, tag):
        lower = tag.lower()
        if lower == "title":
            self.in_title = False
        elif lower == "script":
            if (
                self._script_type
                == "application/ld+json"
            ):
                raw = "".join(
                    self._script_parts
                ).strip()
                if raw:
                    self.json_ld.append(raw)
            self._script_type = None
            self._script_parts = []

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self._script_type is not None:
            self._script_parts.append(data)


def _flatten_json_ld(raw_items):
    values = []

    def visit(value):
        if isinstance(value, dict):
            values.append(value)
            graph = value.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for raw in raw_items:
        try:
            visit(json.loads(raw))
        except (ValueError, TypeError):
            continue

    return values


def _opening_hours_from_json_ld(items):
    values = []

    for item in items:
        raw = (
            item.get("openingHours")
            or item.get("openingHoursSpecification")
        )

        if isinstance(raw, str):
            text = raw.strip()
            if text and text not in values:
                values.append(text)
        elif isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str):
                    text = entry.strip()
                elif isinstance(entry, dict):
                    days = entry.get("dayOfWeek")
                    if isinstance(days, list):
                        day_text = ", ".join(
                            str(day).split("/")[-1]
                            for day in days
                        )
                    else:
                        day_text = str(
                            days or ""
                        ).split("/")[-1]
                    opens = str(
                        entry.get("opens") or ""
                    ).strip()
                    closes = str(
                        entry.get("closes") or ""
                    ).strip()
                    text = " ".join(
                        part
                        for part in (
                            day_text,
                            (
                                f"{opens}-{closes}"
                                if opens and closes
                                else opens or closes
                            ),
                        )
                        if part
                    ).strip()
                else:
                    text = ""

                if text and text not in values:
                    values.append(text)

    return values[:14]


def _prices_from_json_ld(items):
    values = []

    def add(name, price, currency="KRW"):
        label = str(name or "").strip()
        amount = str(price or "").strip()
        if not amount:
            return
        item = {
            "name": label or None,
            "price": amount,
            "currency": str(
                currency or "KRW"
            ).strip() or "KRW",
        }
        if item not in values:
            values.append(item)

    for item in items:
        offers = item.get("offers")
        if isinstance(offers, dict):
            add(
                item.get("name"),
                offers.get("price"),
                offers.get("priceCurrency"),
            )
        elif isinstance(offers, list):
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                add(
                    offer.get("name")
                    or item.get("name"),
                    offer.get("price"),
                    offer.get("priceCurrency"),
                )

        price = item.get("price")
        if price is not None:
            add(
                item.get("name"),
                price,
                item.get("priceCurrency"),
            )

    return values[:12]


def inspect_naver_place_page(url):
    page_url = str(url or "").strip()

    if not _is_allowed_naver_url(page_url):
        return {
            "checked": False,
            "reason": "not_naver_place_url",
            "url": page_url or None,
            "opening_hours": [],
            "prices": [],
        }

    try:
        response = httpx.get(
            page_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
            },
            timeout=httpx.Timeout(
                5.0,
                connect=2.0,
            ),
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return {
            "checked": False,
            "reason": "page_fetch_failed",
            "url": page_url,
            "opening_hours": [],
            "prices": [],
        }

    final_url = str(response.url)
    if (
        response.status_code < 200
        or response.status_code >= 300
        or not _is_allowed_naver_url(final_url)
    ):
        return {
            "checked": False,
            "reason": (
                f"http_{response.status_code}"
            ),
            "url": final_url,
            "opening_hours": [],
            "prices": [],
        }

    parser = _MetadataParser()
    try:
        parser.feed(response.text)
    except Exception:
        pass

    json_ld = _flatten_json_ld(
        parser.json_ld
    )
    title = _strip_tags(
        " ".join(parser.title_parts)
        or parser.meta.get("og:title")
        or ""
    )
    description = _strip_tags(
        parser.meta.get("og:description")
        or parser.meta.get("description")
        or ""
    )
    image_candidate = str(
        parser.meta.get("og:image")
        or parser.meta.get("twitter:image")
        or ""
    ).strip()
    image_url = (
        image_candidate
        if _is_allowed_naver_image_url(
            image_candidate
        )
        else None
    )

    return {
        "checked": True,
        "reason": None,
        "url": final_url,
        "title": title or None,
        "description": description or None,
        "image_url": image_url,
        "opening_hours": (
            _opening_hours_from_json_ld(
                json_ld
            )
        ),
        "prices": _prices_from_json_ld(
            json_ld
        ),
    }


def _search_naver_candidates(
    kakao_business,
    *,
    client_id,
    client_secret,
):
    name = str(
        kakao_business.get("name") or ""
    ).strip()
    address = str(
        kakao_business.get("road_address")
        or kakao_business.get("address")
        or ""
    ).strip()

    if not name:
        return []

    address_tokens = list(
        _address_tokens(address)
    )
    location_hint = " ".join(
        address_tokens[:3]
    )
    query = " ".join(
        part
        for part in (
            name,
            location_hint,
        )
        if part
    ).strip()

    try:
        response = httpx.get(
            NAVER_LOCAL_SEARCH_URL,
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={
                "query": query,
                "display": 5,
                "start": 1,
                "sort": "random",
            },
            timeout=httpx.Timeout(
                5.0,
                connect=2.0,
            ),
        )
    except httpx.HTTPError as exc:
        raise NaverPlaceProviderError(
            "네이버 지역검색 서버에 연결하지 못했습니다."
        ) from exc

    if response.status_code != 200:
        raise NaverPlaceProviderError(
            "네이버 지역검색 요청에 실패했습니다. "
            f"HTTP {response.status_code}"
        )

    payload = response.json()
    items = payload.get("items", [])
    return [
        item
        for item in items
        if isinstance(item, dict)
    ]


def enrich_one_business(
    kakao_business,
    *,
    client_id,
    client_secret,
):
    business = dict(kakao_business)

    try:
        items = _search_naver_candidates(
            business,
            client_id=client_id,
            client_secret=client_secret,
        )
    except NaverPlaceProviderError as exc:
        business["naver"] = {
            "matched": False,
            "page_checked": False,
            "status": "provider_error",
            "message": str(exc),
        }
        return business

    ranked = sorted(
        (
            (
                _match_score(
                    business,
                    item,
                ),
                item,
            )
            for item in items
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )

    if not ranked or ranked[0][0] < 65:
        business["naver"] = {
            "matched": False,
            "page_checked": False,
            "status": "not_matched",
        }
        return business

    score, item = ranked[0]
    link = str(
        item.get("link") or ""
    ).strip()
    page = inspect_naver_place_page(link)

    if (
        not str(
            business.get("image_url") or ""
        ).strip()
        and str(
            page.get("image_url") or ""
        ).strip()
    ):
        business["image_url"] = str(
            page.get("image_url")
        ).strip()
        business["image_source"] = (
            "naver_place"
        )

    business["naver"] = {
        "matched": True,
        "match_score": score,
        "name": _strip_tags(
            item.get("title")
        ),
        "category": _strip_tags(
            item.get("category")
        ),
        "address": str(
            item.get("roadAddress")
            or item.get("address")
            or ""
        ).strip(),
        "link": link or None,
        "page_checked": (
            page.get("checked") is True
        ),
        "page_status": (
            "checked"
            if page.get("checked") is True
            else page.get("reason")
        ),
        "page_url": page.get("url"),
        "page_title": page.get("title"),
        "page_description": (
            page.get("description")
        ),
        "image_url": page.get("image_url"),
        "opening_hours": (
            page.get("opening_hours")
            or []
        ),
        "prices": page.get("prices") or [],
    }

    return business


def enrich_businesses_with_naver(
    businesses,
    *,
    client_id=None,
    client_secret=None,
):
    if not isinstance(businesses, list):
        return []

    safe = [
        dict(item)
        for item in businesses
        if isinstance(item, dict)
    ]

    if not safe:
        return []

    try:
        resolved_id, resolved_secret = (
            _resolve_credentials(
                client_id,
                client_secret,
            )
        )
    except NaverPlaceConfigurationError:
        return [
            {
                **business,
                "naver": {
                    "matched": False,
                    "page_checked": False,
                    "status": "not_configured",
                },
            }
            for business in safe
        ]

    results = [None] * len(safe)

    with ThreadPoolExecutor(
        max_workers=min(4, len(safe)),
    ) as executor:
        future_to_index = {
            executor.submit(
                enrich_one_business,
                business,
                client_id=resolved_id,
                client_secret=resolved_secret,
            ): index
            for index, business in enumerate(safe)
        }

        for future in as_completed(
            future_to_index
        ):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception:
                results[index] = {
                    **safe[index],
                    "naver": {
                        "matched": False,
                        "page_checked": False,
                        "status": "enrichment_error",
                    },
                }

    return [
        result
        for result in results
        if isinstance(result, dict)
    ]

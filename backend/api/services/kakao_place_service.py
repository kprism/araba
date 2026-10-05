import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx


KAKAO_PLACE_HOSTS = {
    "place.map.kakao.com",
}

KAKAO_IMAGE_HOST_SUFFIXES = (
    "kakaocdn.net",
    "daumcdn.net",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Mobile Safari/537.36"
)


class _MetaImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return

        attr = {
            str(key or "").lower(): str(value or "")
            for key, value in attrs
        }
        key = (
            attr.get("property")
            or attr.get("name")
            or ""
        ).strip().lower()
        value = attr.get("content", "").strip()

        if key in {
            "og:image",
            "og:image:url",
            "twitter:image",
        } and value:
            self.images.append(
                html.unescape(value)
            )


def _is_kakao_place_url(value):
    try:
        parsed = urlparse(
            str(value or "").strip()
        )
    except ValueError:
        return False

    return (
        parsed.scheme in ("http", "https")
        and (parsed.hostname or "").lower()
        in KAKAO_PLACE_HOSTS
    )


def _is_kakao_image_url(value):
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
            for suffix in KAKAO_IMAGE_HOST_SUFFIXES
        )
    )


def _first_kakao_image(
    page_url,
    html_text,
):
    parser = _MetaImageParser()

    try:
        parser.feed(html_text)
    except Exception:
        pass

    for raw in parser.images:
        candidate = urljoin(
            page_url,
            raw,
        )
        if _is_kakao_image_url(candidate):
            return candidate

    # 일부 장소 페이지는 대표사진을 메타태그가 아니라
    # 초기 렌더링 데이터 안에 넣는다. 카카오 CDN의 실제 URL만 허용한다.
    escaped = re.findall(
        r'https?:\\?/\\?/[^"\'<>\s]+',
        html_text,
        flags=re.IGNORECASE,
    )

    for raw in escaped:
        candidate = (
            raw
            .replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("&amp;", "&")
        )
        if _is_kakao_image_url(candidate):
            lowered = candidate.lower()
            if (
                "local" in lowered
                or "place" in lowered
                or "cthumb" in lowered
            ):
                return candidate

    return None


def inspect_kakao_place_page(place_url):
    page_url = str(
        place_url or ""
    ).strip()

    if not _is_kakao_place_url(page_url):
        return {
            "checked": False,
            "image_url": None,
            "reason": "not_kakao_place_url",
        }

    try:
        response = httpx.get(
            page_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": (
                    "ko-KR,ko;q=0.9,en;q=0.7"
                ),
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
            "image_url": None,
            "reason": "page_fetch_failed",
        }

    final_url = str(response.url)

    if (
        response.status_code < 200
        or response.status_code >= 300
        or not _is_kakao_place_url(final_url)
    ):
        return {
            "checked": False,
            "image_url": None,
            "reason": (
                f"http_{response.status_code}"
            ),
        }

    return {
        "checked": True,
        "image_url": _first_kakao_image(
            final_url,
            response.text,
        ),
        "reason": None,
    }


def _enrich_one_business(business):
    item = dict(business)
    page = inspect_kakao_place_page(
        item.get("place_url")
    )

    item["kakao_page_checked"] = (
        page.get("checked") is True
    )

    image_url = str(
        page.get("image_url") or ""
    ).strip()
    if image_url:
        item["image_url"] = image_url
        item["image_source"] = (
            "kakao_place"
        )

    return item


def enrich_businesses_with_kakao_pages(
    businesses,
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

    results = [None] * len(safe)

    with ThreadPoolExecutor(
        max_workers=min(6, len(safe)),
    ) as executor:
        future_to_index = {
            executor.submit(
                _enrich_one_business,
                business,
            ): index
            for index, business in enumerate(safe)
        }

        for future in as_completed(
            future_to_index
        ):
            index = future_to_index[future]
            try:
                results[index] = (
                    future.result()
                )
            except Exception:
                results[index] = {
                    **safe[index],
                    "kakao_page_checked": False,
                }

    return [
        result
        for result in results
        if isinstance(result, dict)
    ]

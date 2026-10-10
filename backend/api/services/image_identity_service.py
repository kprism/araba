TRUSTED_IMAGE_SOURCES = {
    "google_places_verified",
}


def enforce_business_image_identity(business):
    item = dict(business)
    image_url = str(
        item.get("image_url") or ""
    ).strip()
    if not image_url:
        return item

    source = str(
        item.get("image_source") or ""
    ).strip()

    verified = (
        item.get("image_identity_verified") is True
        or source in TRUSTED_IMAGE_SOURCES
    )

    if (
        source in {"naver_place", "kakao_place"}
        and item.get("image_identity_verified") is True
    ):
        verified = True

    if verified:
        item["image_identity_verified"] = True
        return item

    item["unverified_image_url"] = image_url
    item["unverified_image_source"] = source or None
    item["image_url"] = None
    item["image_source"] = "identity_unverified_hidden"
    item["image_identity_verified"] = False
    return item


def enforce_business_images(businesses):
    return [
        enforce_business_image_identity(item)
        for item in businesses
        if isinstance(item, dict)
    ]

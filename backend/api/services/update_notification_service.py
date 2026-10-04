import jwt
from firebase_admin import get_app, initialize_app, messaging
from jwt import PyJWKClient


GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_AUDIENCE = "araba-update-notifier"
GITHUB_REPOSITORY = "kprism/araba"
GITHUB_MAIN_REF = "refs/heads/main"
GITHUB_WORKFLOW_PREFIX = (
    "kprism/araba/.github/workflows/"
    "android-dev-apk.yml@"
)
GITHUB_JWKS_URL = (
    "https://token.actions.githubusercontent.com/"
    ".well-known/jwks"
)

UPDATE_TOPIC = "araba-dev-updates"
UPDATE_APK_URL = (
    "https://github.com/kprism/araba/releases/download/"
    "dev-latest/araba-dev.apk"
)

_jwk_client = PyJWKClient(GITHUB_JWKS_URL)


def verify_github_actions_token(token):
    signing_key = _jwk_client.get_signing_key_from_jwt(token)

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=GITHUB_OIDC_AUDIENCE,
        issuer=GITHUB_OIDC_ISSUER,
        options={
            "require": [
                "exp",
                "iat",
                "iss",
                "aud",
                "repository",
                "ref",
            ]
        },
    )

    if claims.get("repository") != GITHUB_REPOSITORY:
        raise ValueError("허용되지 않은 GitHub 저장소입니다.")

    if claims.get("ref") != GITHUB_MAIN_REF:
        raise ValueError("main 브랜치에서만 알림을 보낼 수 있습니다.")

    workflow_ref = str(claims.get("workflow_ref", ""))

    if not workflow_ref.startswith(GITHUB_WORKFLOW_PREFIX):
        raise ValueError("허용되지 않은 GitHub workflow입니다.")

    return claims


def ensure_firebase_app():
    try:
        return get_app()
    except ValueError:
        return initialize_app(
            options={"projectId": "araba-dev"}
        )


def subscribe_device_to_updates(token):
    token = str(token).strip()

    if len(token) < 40:
        raise ValueError("유효한 FCM 토큰이 필요합니다.")

    app = ensure_firebase_app()
    response = messaging.subscribe_to_topic(
        [token],
        UPDATE_TOPIC,
        app=app,
    )

    if response.failure_count:
        raise ValueError("FCM 업데이트 토픽 등록에 실패했습니다.")

    return {
        "success_count": response.success_count,
        "failure_count": response.failure_count,
        "topic": UPDATE_TOPIC,
    }


def send_update_notification():
    app = ensure_firebase_app()

    message = messaging.Message(
        topic=UPDATE_TOPIC,
        notification=messaging.Notification(
            title="ARABA 새 버전 준비됨",
            body="알림을 눌러 최신 개발 버전으로 업데이트하세요.",
        ),
        data={
            "url": UPDATE_APK_URL,
            "type": "app_update",
        },
        android=messaging.AndroidConfig(
            priority="high",
        ),
    )

    return messaging.send(
        message,
        app=app,
    )

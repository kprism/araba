# ARABA

**알아봐줘 | AI 전화검색 플랫폼**

> 검색해도 없으면, AI가 직접 전화해서 알아봅니다.

ARABA는 사용자가 원하는 현실 정보를 웹이나 기존 데이터에서 찾을 수 없을 때,
AI가 업체에 직접 전화하여 가격, 재고, 가능 시간, 조건 등을 확인하고
결과를 사용자에게 전달하는 AI 전화검색 플랫폼입니다.

## Core Flow

사용자 요청
→ Mission 생성
→ 기존 Fresh DB 확인
→ 업체 후보 탐색
→ 필요한 업체에 AI 전화
→ 결과 구조화
→ 비교 결과 제공
→ 사용자 승인
→ 예약/변경/취소
→ Fresh Fact DB 갱신

## Platforms

- Android
- iOS
- PC Web/PWA

## Architecture

- Mobile: Flutter
- Backend: Django + Django REST Framework
- Database: PostgreSQL
- Queue: Redis + Celery
- AI: OpenAI API
- Voice AI: OpenAI Realtime API
- Telephony: SIP / Twilio
- Place Search: Kakao Local API
- Push: Firebase Cloud Messaging / APNs
- Cloud: Google Cloud Platform

## Repository Structure

    backend/   Django API, Mission Engine, AI/Call orchestration
    mobile/    Flutter Android/iOS application
    web/       PC Web/PWA
    infra/     Cloud and deployment infrastructure
    docs/      Architecture, product and development documentation

## Development Priority

The first POC is not the mobile UI.

The first critical experiment is:

**ARABA AI → real phone call → natural Korean conversation → structured result**

Only after the voice POC passes the quality gate will the full application be expanded.

## Security

Never commit real API keys, passwords, tokens or telephone credentials.

Use:

- GitHub Codespaces Secrets
- GitHub Actions Secrets
- Google Secret Manager
- Environment variables

## Status

POC Development

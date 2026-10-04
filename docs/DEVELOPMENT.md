# ARABA Development Environment

## Repository

This repository is the ARABA monorepo.

## Directory Structure

backend/
    Django API and Mission Engine

mobile/
    Flutter Android/iOS application

web/
    PC Web/PWA

infra/
    GCP, deployment and infrastructure configuration

docs/
    architecture, API and product documentation

## Secret Policy

Real API keys and credentials MUST NOT be committed to GitHub.

Secrets must be stored using:

- GitHub Codespaces Secrets
- GitHub Actions Secrets
- Google Secret Manager
- local environment variables

## Development Principle

Every development day must produce a testable artifact.

No feature is considered complete without verification.

# DAY 02 - OpenAI / Voice POC Preparation

## Objective

Prepare ARABA for its first critical POC:

ARABA -> AI voice -> real telephone call -> Korean conversation -> structured result.

## Development rule

Before modifying an existing feature:

1. Inspect the current GitHub implementation.
2. Identify the existing file, class and function responsible.
3. Inspect callers and dependencies.
4. Modify or refactor the existing implementation.
5. Do not append duplicate replacement implementations.
6. Test before commit.
7. Push the verified state to GitHub.

## Secret policy

Real credentials must never be committed.

Local development secrets belong in `.env`.
Production secrets will use Google Secret Manager.

## Voice architecture

The initial experiment will evaluate OpenAI GPT-Live / SIP telephony.

The telephony layer must remain replaceable so ARABA is not permanently
coupled to one telephone provider.

## Gate

The voice POC must demonstrate:

- natural Korean conversation
- acceptable response latency
- interruption / barge-in handling
- mission objective retention
- condition changes during conversation
- clean conversation termination

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

api_key = os.getenv("OPENAI_API_KEY")

print("=" * 55)
print(" ARABA OPENAI ENVIRONMENT CHECK")
print("=" * 55)

if not api_key:
    print("OPENAI_API_KEY: NOT CONFIGURED")
    print()
    print("Environment structure is ready.")
    print("Next step: configure the API key securely.")
    sys.exit(0)

masked = api_key[:7] + "..." + api_key[-4:] if len(api_key) > 12 else "***"

print(f"OPENAI_API_KEY: CONFIGURED ({masked})")
print("Environment structure is ready.")

"""Environment, API key, and preflight health checks."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Ensure repository root is on sys.path even when run directly as a script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from socratic_tutor import config


def check_api_key() -> bool:
    openrouter_key = os.getenv("OPENROUTER_API_KEY") or config.OPENROUTER_API_KEY
    openai_key = os.getenv("OPENAI_API_KEY") or config.OPENAI_API_KEY

    if not openrouter_key and not openai_key:
        print("❌ ERROR: Neither OPENROUTER_API_KEY nor OPENAI_API_KEY is configured in .env or environment.")
        return False

    if openrouter_key:
        print("Validating OpenRouter API key with auth endpoint...")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "User-Agent": "SocraticTutor/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                key_data = data.get("data", {})
                label = key_data.get("label") or "Default Key"
                usage = key_data.get("usage", 0.0)
                limit = key_data.get("limit")
                limit_str = f"${limit:.2f}" if limit is not None else "Unlimited"
                print(f"✅ OpenRouter API key is VALID and ACTIVE.")
                print(f"   Label: {label}")
                print(f"   Usage: ${usage:.4f} (Limit: {limit_str})")
                return True
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("❌ OpenRouter API key is INVALID or EXPIRED (HTTP 401 Unauthorized).")
            elif e.code == 402:
                print("⚠️ OpenRouter API key is valid, but account is out of credits (HTTP 402 Payment Required).")
            else:
                print(f"❌ OpenRouter API error: HTTP {e.code} ({e.reason})")
            return False
        except Exception as e:
            print(f"⚠️ Could not verify OpenRouter key online (network check skipped: {e}).")
            print("   Key string is present in environment.")
            return True

    if openai_key:
        print("Validating OpenAI API key with models endpoint...")
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={
                "Authorization": f"Bearer {openai_key}",
                "User-Agent": "SocraticTutor/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("✅ OpenAI API key is VALID and ACTIVE.")
                return True
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("❌ OpenAI API key is INVALID or EXPIRED (HTTP 401 Unauthorized).")
            else:
                print(f"❌ OpenAI API error: HTTP {e.code} ({e.reason})")
            return False
        except Exception as e:
            print(f"⚠️ Could not verify OpenAI key online (network check skipped: {e}).")
            print("   Key string is present in environment.")
            return True

    return False


def check_index() -> None:
    chunks_path = config.INDEX_DIR / "chunks.json"
    if chunks_path.exists() and chunks_path.stat().st_size > 0:
        print(f"✅ Knowledge Base index is ready ({chunks_path.name}, {chunks_path.stat().st_size // 1024} KB).")
    else:
        print(f"⚠️ Knowledge Base index is missing in {config.INDEX_DIR}. Run `make index` to build it.")


def check_server() -> None:
    url = f"http://{config.HOST}:{config.PORT}/healthz"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                print(f"✅ Local server is running and healthy at http://{config.HOST}:{config.PORT}/")
    except Exception:
        print(f"ℹ️  Local server is not currently running (start anytime with `make app`).")


def main() -> None:
    print("=== Socratic Tutor Preflight Check ===")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    
    key_ok = check_api_key()
    check_index()
    check_server()

    print(f"Target Chapters: {', '.join(config.TARGET_CHAPTERS)}")
    print("=======================================")
    if not key_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()

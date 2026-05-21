import os
import sys

def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"[config] FATAL: переменная окружения '{key}' не задана или пуста", flush=True)
        sys.exit(1)
    return val

BOT_TOKEN          = _require("BOT_TOKEN")
OPENROUTER_API_KEY = _require("OPENROUTER_API_KEY")
CHANNEL_ID         = _require("CHANNEL_ID")
BASE_WEBHOOK_URL   = _require("BASE_WEBHOOK_URL")

try:
    ALLOWED_USER_ID = int(_require("ALLOWED_USER_ID"))
except ValueError:
    print("[config] FATAL: ALLOWED_USER_ID должен быть целым числом", flush=True)
    sys.exit(1)

PORT = int(os.environ.get("PORT", 8080))

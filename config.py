import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
CHANNEL_ID = os.environ["CHANNEL_ID"]
BASE_WEBHOOK_URL = os.environ["BASE_WEBHOOK_URL"]
PORT = int(os.environ.get("PORT", 8080))

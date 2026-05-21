import base64
import requests
from config import OPENROUTER_API_KEY, SYSTEM_PROMPT

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash"


def process_audio_to_post(audio_bytes: bytes) -> str:
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SYSTEM_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:audio/ogg;base64,{audio_base64}"
                        },
                    },
                ],
            }
        ],
    }

    try:
        response = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        data = response.json()
    except Exception as e:
        return f"Ошибка запроса: {e}"

    if "error" in data:
        return f"Ошибка OpenRouter: {data['error']}"

    return data["choices"][0]["message"]["content"]

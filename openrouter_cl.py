import base64
import json
import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-3.5-flash"

TRANSCRIPTION_PROMPT = (
    "Ты — транскрибатор голосовых заметок. Переведи аудиозапись в текст максимально точно, "
    "сохраняя все слова автора. Выдай ТОЛЬКО текст транскрипции, без каких-либо комментариев."
)

PR_SYSTEM_PROMPT = """Ты — опытный PR-менеджер и контент-редактор Telegram-канала "Dental Авангард I".
Автор канала — Александр, 16-летний будущий хирург-стоматолог, строящий путь к сети из 100 клиник.
Ценности канала: вера в Бога, жёсткая дисциплина, спорт, стоматология, лидерство, ЕГЭ, Питер.
Аудитория ("Денталы"): люди, разделяющие эти ценности и смотрящие на Александра как на лидера и кумира.

Твои задачи:
1. Проанализировать сырые мысли автора.
2. Составить сильный, структурированный пост для Telegram.
3. Провести аудит рисков: какие мысли отфильтрованы, смягчены или переформулированы, чтобы не отторгнуть аудиторию.

Правила для поста:
- Начинается СТРОГО с "Денталы, всем привет." или "Денталы, на связи."
- Стиль: уверенный, прагматичный, без воды, без итогов вроде "Подписывайтесь".
- Форматирование: списки (•), жирный текст для ключевых мыслей, чёткие абзацы.
- В самом конце ОБЯЗАТЕЛЬНО: ⚡️ WAY TO DENTAL-100 | #философияАвангарда 🧠

Ответь СТРОГО в формате JSON — без markdown-обёртки, только чистый JSON:
{
  "post_text": "Текст готового поста",
  "audit": "Краткий аудит рисков от Gemini 3.5 Flash для Александра"
}"""


def transcribe_audio(audio_bytes: bytes, api_key: str) -> str:
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TRANSCRIPTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:audio/ogg;base64,{audio_base64}"},
                    },
                ],
            }
        ],
    }

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        data = response.json()
    except Exception as e:
        return f"Ошибка транскрипции: {e}"

    if "error" in data:
        return f"Ошибка OpenRouter: {data['error']}"

    return data["choices"][0]["message"]["content"].strip()


def get_structured_post(text: str, api_key: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": PR_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        data = response.json()
    except Exception as e:
        return {"post_text": "", "audit": f"Ошибка запроса: {e}"}

    if "error" in data:
        return {"post_text": "", "audit": f"Ошибка OpenRouter: {data['error']}"}

    raw = data["choices"][0]["message"]["content"].strip()

    # Снять markdown-обёртку, если модель всё же добавила ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"post_text": raw, "audit": "Не удалось распарсить JSON-ответ от модели."}

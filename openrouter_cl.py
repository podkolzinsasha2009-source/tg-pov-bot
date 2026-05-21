import base64
import json
import traceback

import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash"

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
  "audit": "Краткий аудит рисков от Gemini для Александра"
}"""


INTENT_SYSTEM_PROMPT = """Ты — классификатор намерений для Telegram-бота Александра.
Тебе придёт транскрипция его голосовой заметки. Верни ОДНО СЛОВО — категорию намерения:

SAVE_THOUGHT   — обычная мысль, рассказ, наблюдение (учёба, химия, спорт, стоматология, жизнь и т.д.)
EDIT_POST      — просьба изменить, переписать, убрать или добавить что-то в текущий черновик поста
PUBLISH_POST   — команда опубликовать / выложить / отправить пост в канал
SHOW_POST      — просьба показать / прочитать текущий готовый черновик поста

Отвечай ТОЛЬКО одним из этих четырёх слов, без точек, кавычек и пояснений."""


def _api_error_message(data: dict) -> str:
    err = data.get("error", {})
    if isinstance(err, dict):
        return err.get("message", str(err))
    return str(err)


def classify_intent(user_text: str, api_key: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    }

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        print(f"[intent] HTTP {response.status_code}")
        data = response.json()
    except Exception as e:
        print(f"[intent] ошибка запроса: {e}")
        return "SAVE_THOUGHT"

    if "error" in data:
        print(f"[intent] ошибка API: {_api_error_message(data)}")
        return "SAVE_THOUGHT"

    try:
        intent = data["choices"][0]["message"]["content"].strip().upper()
    except (KeyError, IndexError):
        print(f"[intent] неожиданный ответ: {data}")
        return "SAVE_THOUGHT"

    valid = {"SAVE_THOUGHT", "EDIT_POST", "PUBLISH_POST", "SHOW_POST"}
    if intent not in valid:
        print(f"[intent] неизвестная категория '{intent}', fallback → SAVE_THOUGHT")
        return "SAVE_THOUGHT"

    print(f"[intent] → {intent}")
    return intent


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
        print(f"[transcribe] HTTP {response.status_code}")
        data = response.json()
    except Exception as e:
        print(f"[transcribe] ошибка запроса: {e}")
        traceback.print_exc()
        return f"Ошибка транскрипции: {e}"

    if "error" in data:
        msg = _api_error_message(data)
        print(f"[transcribe] ошибка API: {msg}")
        return f"Ошибка OpenRouter: {msg}"

    try:
        content = data["choices"][0]["message"]["content"]
        if content is None:
            print(f"[transcribe] content=None, полный ответ: {data}")
            return "Ошибка: модель вернула пустой ответ (content: null)"
        return content.strip()
    except (KeyError, IndexError) as e:
        print(f"[transcribe] неожиданный ответ: {data}")
        return f"Неожиданный ответ API: {data}"


EDIT_SYSTEM_PROMPT = """Ты — опытный PR-менеджер Telegram-канала "Dental Авангард I".
Тебе дан готовый черновик поста и голосовая команда-правка от Александра.
Примень правку точно, сохрани фирменный стиль канала и верни СТРОГО JSON без markdown-обёртки:
{
  "post_text": "Обновлённый текст поста",
  "audit": "Что именно изменено и почему"
}

Фирменный стиль:
- Начинается со "Денталы, всем привет." или "Денталы, на связи."
- Уверенный, прагматичный тон; списки (•); жирный для ключевых мыслей.
- В конце ОБЯЗАТЕЛЬНО: ⚡️ WAY TO DENTAL-100 | #философияАвангарда 🧠"""


def edit_current_post(old_post: str, edit_instruction: str, api_key: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": EDIT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"ТЕКУЩИЙ ЧЕРНОВИК:\n{old_post}\n\n"
                    f"КОМАНДА-ПРАВКА ОТ АЛЕКСАНДРА:\n{edit_instruction}"
                ),
            },
        ],
    }

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        print(f"[edit_post] HTTP {response.status_code}")
        data = response.json()
    except Exception as e:
        print(f"[edit_post] ошибка запроса: {e}")
        traceback.print_exc()
        return {"post_text": old_post, "audit": f"Ошибка запроса: {e}"}

    if "error" in data:
        msg = _api_error_message(data)
        print(f"[edit_post] ошибка API: {msg}")
        return {"post_text": old_post, "audit": f"Ошибка OpenRouter: {msg}"}

    try:
        raw = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        print(f"[edit_post] неожиданный ответ: {data}")
        return {"post_text": old_post, "audit": f"Неожиданный ответ API: {data}"}

    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"post_text": raw, "audit": "Не удалось распарсить JSON-ответ от модели."}


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
        print(f"[post] HTTP {response.status_code}")
        data = response.json()
    except Exception as e:
        print(f"[post] ошибка запроса: {e}")
        traceback.print_exc()
        return {"post_text": "", "audit": f"Ошибка запроса: {e}"}

    if "error" in data:
        msg = _api_error_message(data)
        print(f"[post] ошибка API: {msg}")
        return {"post_text": "", "audit": f"Ошибка OpenRouter: {msg}"}

    try:
        raw = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        print(f"[post] неожиданный ответ: {data}")
        return {"post_text": "", "audit": f"Неожиданный ответ API: {data}"}

    # Снять markdown-обёртку, если модель всё же добавила ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"post_text": raw, "audit": "Не удалось распарсить JSON-ответ от модели."}

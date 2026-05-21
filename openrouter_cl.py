import base64
import json
import sqlite3
import traceback

import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL   = "google/gemini-2.5-flash"
DB_PATH = "thoughts.db"

TRANSCRIPTION_PROMPT = (
    "Ты — транскрибатор голосовых заметок. Переведи аудиозапись в текст максимально точно, "
    "сохраняя все слова автора. Выдай ТОЛЬКО текст транскрипции, без каких-либо комментариев."
)

PR_SYSTEM_PROMPT = """Ты — опытный PR-менеджер, который пишет посты для личного бренда "Dental Авангард I". Автор канала — Александр, 16-летний будущий хирург-стоматолог, целеустремленный, глубоко верующий в Бога, жестко дисциплинированный, занимающийся спортом, химией и биологией.
Тон подачи: уверенный, харизматичный, вдохновляющий, без капли «воды», банальных фраз и клише.

Твоя задача — упаковать хаотичные мысли автора за день в один мощный, премиальный пост, полностью копируя визуальную верстку и структуру канала Владимира I.

Жесткие правила оформления текста (используй HTML-разметку):
1. ЗАГОЛОВОК: Пост должен СТРОГО начинаться с жирного цепляющего тезиса/заголовка, обернутого в теги <b>...</b>. В конце заголовка или внутри него обязательно используй один уместный анимированный эмодзи.
2. АРХИТЕКТУРА ТЕКСТА: Разделяй текст на короткие, емкие абзацы (1–3 предложения). Между абзацами ОБЯЗАТЕЛЬНО должна быть пустая строка, чтобы текст «дышал».
3. ВЫДЕЛЕНИЯ И ЦИТАТЫ:
   - Ключевые тезисы и важные маркеры выделяй жирным: <b>жирный текст</b>.
   - Особые инсайты, выводы или глубокие акценты выделяй курсивом: <i>курсив</i>.
   - Прямую речь, правила, законы жизни или масштабные философские размышления ОФОРМЛЯЙ СТРОГО как блок цитаты через тег <blockquote>текст цитаты</blockquote>.
4. АНИМИРОВАННЫЕ ЭМОДЗИ: Допускается использовать только те теги премиум-эмодзи, которые переданы в списке ниже. Лимит: 3–5 штук на весь пост, строго к месту (в заголовках или списках). Обычные Unicode-эмодзи без тегов использовать ЗАПРЕЩЕНО.

Доступные премиум-эмодзи:
{EMOJI_DICT}

ПОДВАЛ ПОСТА (НАВИГАЦИЯ):
В самый конец поста, строго после текста и хэштега #философияАвангарда (который ставится для глубоких постов), в одну строчку без переносов добавь навигационное меню ровно в таком HTML-формате:
<b><a href="https://t.me/boost/dental_avangard">Boost ⚡</a> | <a href="#">Map 🎯</a> | <a href="https://t.me/Dental_Avangard_chat">Chat 💬</a></b>

Выходной формат должен быть СТРОГО в JSON без markdown-обёртки:
{
  "post_text": "готовый текст поста со всей HTML-разметкой, цитатами и подвалом навигации",
  "audit": "краткий технический комментарий, почему пост оформлен именно так"
}"""


INTENT_SYSTEM_PROMPT = """Ты — классификатор намерений для Telegram-бота Александра.
Тебе придёт транскрипция его голосовой заметки. Верни ОДНО СЛОВО — категорию намерения:

SAVE_THOUGHT   — обычная мысль, рассказ, наблюдение (учёба, химия, спорт, стоматология, жизнь и т.д.)
EDIT_POST      — просьба изменить, переписать, убрать или добавить что-то в текущий черновик поста
PUBLISH_POST   — команда опубликовать / выложить / отправить пост в канал
SHOW_POST      — просьба показать / прочитать текущий готовый черновик поста

Отвечай ТОЛЬКО одним из этих четырёх слов, без точек, кавычек и пояснений."""


def _load_emoji_section() -> str:
    """Читает таблицу emojis и возвращает готовый блок для системного промта."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT emoji_char, custom_emoji_id FROM emojis ORDER BY emoji_char"
            ).fetchall()
    except Exception as e:
        print(f"[emoji_section] не удалось прочитать БД: {e}")
        return "Пользовательских эмодзи пока нет. Используй только текстовое форматирование, без эмодзи."

    if not rows:
        return "Пользовательских эмодзи пока нет. Используй только текстовое форматирование, без эмодзи."

    tags = "\n".join(
        f'• <tg-emoji emoji-id="{eid}">{char}</tg-emoji>'
        for char, eid in rows
    )
    return (
        f"Используй ИСКЛЮЧИТЕЛЬНО теги из списка ниже. Не более 3–5 на весь пост, строго к месту.\n"
        f"Обычные Unicode-эмодзи без тегов — ЗАПРЕЩЕНЫ (портят премиальный вид поста).\n\n"
        f"Разрешённый словарь:\n{tags}"
    )


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


EDIT_SYSTEM_PROMPT = """Ты — ИИ-редактор личного бренда "Dental Авангард I". Твоя задача — внести точечные изменения в текущий черновик поста на основе голосовых правок Александра, полностью сохраняя премиальный стиль, структуру и HTML-верстку.

Жесткие правила редактирования:
1. Меняй только то, о чем просит автор. Сохраняй общую структуру: жирный цепляющий заголовок (<b>...</b>), короткие абзацы с пустыми строками между ними.
2. ТЕКСТОВОЕ ФОРМАТИРОВАНИЕ (HTML):
   - Заголовки, акценты: <b>текст</b>
   - Мысли, инсайты: <i>текст</i>
   - Правила, цитаты, глубокая философия: СТРОГО внутри <blockquote>текст</blockquote>.
3. АНИМИРОВАННЫЕ ЭМОДЗИ: Используй только теги из списка ниже (3–5 на пост). Обычные смайлики запрещены.
{EMOJI_DICT}

ПОДВАЛ ПОСТА (НАВИГАЦИЯ):
В самом конце текста (после хэштега #философияАвангарда, если он есть) обязательно должна оставаться навигационная строка СТРОГО в одну линию:
<b><a href="https://t.me/boost/dental_avangard">Boost ⚡</a> | <a href="#">Map 🎯</a> | <a href="https://t.me/Dental_Avangard_chat">Chat 💬</a></b>

Выходной формат СТРОГО JSON без markdown-обёртки:
{
  "post_text": "обновленный текст поста с сохраненной HTML-разметкой и подвалом навигации",
  "audit": "что именно было изменено по запросу автора"
}"""


def edit_current_post(old_post: str, edit_instruction: str, api_key: str) -> dict:
    system_prompt = EDIT_SYSTEM_PROMPT.replace("{EMOJI_DICT}", _load_emoji_section())
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
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
    system_prompt = PR_SYSTEM_PROMPT.replace("{EMOJI_DICT}", _load_emoji_section())
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
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

import base64
import json
import re
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

Твоя задача — упаковать хаотичные мысли автора за день в один мощный, премиальный пост.

━━━━━━━━━━━━━━━━━━━━━
ФОРМАТИРОВАНИЕ: СТРОГО TELEGRAM MARKDOWNV2
━━━━━━━━━━━━━━━━━━━━━
Используй ТОЛЬКО синтаксис MarkdownV2. HTML-теги ПОЛНОСТЬЮ ЗАПРЕЩЕНЫ.

Разрешённые маркеры:
• Жирный:       *текст*   (одна звёздочка — НЕ две)
• Курсив:       _текст_
• Подчёркнутый: __текст__
• Зачёркнутый:  ~текст~
• Спойлер:      ||текст||
• Моно:         `текст`
• Цитата:       >текст    (> в самом начале строки)
• Ссылка:       [текст](url)

⚠️ ОБЯЗАТЕЛЬНОЕ ЭКРАНИРОВАНИЕ СПЕЦСИМВОЛОВ:
Символы  _ * [ ] ( ) ~ ` > # + - = | { } . !  встречающиеся в ОБЫЧНОМ ТЕКСТЕ
(не как маркеры форматирования) — ОБЯЗАТЕЛЬНО экранируй обратным слэшем.
Примеры: "в 20\.11"  "это важно\!"  "Dental\_Авангард"  "\#философияАвангарда"

━━━━━━━━━━━━━━━━━━━━━
СТРУКТУРА ПОСТА
━━━━━━━━━━━━━━━━━━━━━
1. ЗАГОЛОВОК: *жирная цепляющая фраза + эмодзи из разрешённого списка*
2. ТЕЛО: абзацы по 1–3 предложения, разделённые пустой строкой.
   Списки — через эмодзи-маркеры из разрешённого списка.
   Прямая речь / глубокая мысль — через цитату: >текст
3. ПОДВАЛ: для глубоких постов добавь \#философияАвангарда
4. НАВИГАЦИЯ (последней строкой, одной строкой):
*[Boost ⚡](https://t.me/boost/dental_avangard) \| [Map 🎯](#) \| [Chat 💬](https://t.me/Dental_Avangard_chat)*

━━━━━━━━━━━━━━━━━━━━━
ДОСТУПНЫЕ ЭМОДЗИ
━━━━━━━━━━━━━━━━━━━━━
{EMOJI_DICT}

━━━━━━━━━━━━━━━━━━━━━
ЗАДАЧИ
━━━━━━━━━━━━━━━━━━━━━
1. Проанализировать сырые мысли автора.
2. Составить сильный пост строго по правилам MarkdownV2 выше.
3. Провести аудит рисков: что отфильтровано, смягчено или переформулировано и почему.

Ответь СТРОГО в формате JSON без markdown-обёртки, только чистый JSON:
{
  "post_text": "готовый текст поста в формате MarkdownV2 с правильным экранированием",
  "audit": "краткий технический аудит"
}"""


INTENT_SYSTEM_PROMPT = """Ты — классификатор намерений для Telegram-бота Александра.
Тебе придёт транскрипция его голосовой заметки. Верни ОДНО СЛОВО — категорию намерения:

SAVE_THOUGHT   — обычная мысль, рассказ, наблюдение (учёба, химия, спорт, стоматология, жизнь и т.д.)
EDIT_POST      — просьба изменить, переписать, убрать или добавить что-то в текущий черновик поста
PUBLISH_POST   — команда опубликовать / выложить / отправить пост в канал
SHOW_POST      — просьба показать / прочитать текущий готовый черновик поста

Отвечай ТОЛЬКО одним из этих четырёх слов, без точек, кавычек и пояснений."""


def _load_emoji_section() -> str:
    """Читает таблицу emojis и возвращает список Unicode-символов для системного промта."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT emoji_char FROM emojis ORDER BY emoji_char"
            ).fetchall()
    except Exception as e:
        print(f"[emoji_section] не удалось прочитать БД: {e}")
        return "Используй подходящие Unicode-эмодзи по смыслу (3–5 на пост)."

    if not rows:
        return "Используй подходящие Unicode-эмодзи по смыслу (3–5 на пост)."

    chars = " ".join(row[0] for row in rows)
    return f"Используй ТОЛЬКО эти эмодзи (3–5 на пост, строго к месту): {chars}"


# ---------------------------------------------------------------------------
# MarkdownV2 escaping
# ---------------------------------------------------------------------------

# Spans whose content must NOT be re-escaped (bold, italic, links, code, etc.)
_FMT_SPAN = re.compile(
    r'```[\s\S]*?```'            # ```code block```
    r'|`[^`\n]+`'                # `inline code`
    r'|\*[^*\n]+\*'              # *bold*
    r'|__[^_\n]+__'              # __underline__
    r'|_[^_\n]+_'                # _italic_
    r'|~[^~\n]+~'                # ~strikethrough~
    r'|\|\|[^|\n]+\|\|'          # ||spoiler||
    r'|\[[^\]\n]+\]\([^)\n]+\)'  # [link](url)
    r'|\\.',                     # \X already-escaped char
    re.DOTALL,
)

# Special characters to escape in plain-text segments
_PLAIN_ESC = re.compile(r'([_*\[\]()~`>#+=|{}.!\-\\])')


def escape_md(text: str) -> str:
    """
    Escape Telegram MarkdownV2 special characters in plain-text segments,
    leaving all formatting spans (*bold*, _italic_, [links](url), etc.) untouched.
    """
    result: list = []
    cursor = 0
    for m in _FMT_SPAN.finditer(text):
        # Escape plain text between previous match end and this match start
        plain = text[cursor:m.start()]
        result.append(_PLAIN_ESC.sub(r'\\\1', plain))
        # Keep formatting span exactly as-is
        result.append(m.group())
        cursor = m.end()
    # Escape any trailing plain text
    result.append(_PLAIN_ESC.sub(r'\\\1', text[cursor:]))
    return ''.join(result)


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


EDIT_SYSTEM_PROMPT = """Ты — ИИ-редактор личного бренда "Dental Авангард I". Твоя задача — внести точечные изменения в текущий черновик поста на основе голосовых правок Александра, полностью сохраняя стиль и MarkdownV2-верстку.

Жесткие правила редактирования:
1. Меняй ТОЛЬКО то, о чём просит автор. Сохраняй структуру: *жирный заголовок*, абзацы с пустыми строками.
2. ФОРМАТИРОВАНИЕ — строго MarkdownV2, HTML-теги ЗАПРЕЩЕНЫ:
   - Жирный:  *текст*  (одна звёздочка)
   - Курсив:  _текст_
   - Цитата:  >текст
   - Ссылка:  [текст](url)
3. ЭКРАНИРОВАНИЕ: все спецсимволы _ * [ ] ( ) ~ ` > # + - = | { } . ! в обычном тексте — экранируй: \. \! \- и т.д.
4. ЭМОДЗИ: используй только из списка ниже (3–5 на пост), вставляй как Unicode-символы.
{EMOJI_DICT}

ПОДВАЛ (обязателен в конце, одной строкой):
*[Boost ⚡](https://t.me/boost/dental_avangard) \| [Map 🎯](#) \| [Chat 💬](https://t.me/Dental_Avangard_chat)*

Выходной формат СТРОГО JSON без markdown-обёртки:
{
  "post_text": "обновлённый текст поста в MarkdownV2 с правильным экранированием",
  "audit": "что именно изменено по запросу автора"
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

import asyncio
import io
import traceback

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import db
from config import ALLOWED_USER_ID, BASE_WEBHOOK_URL, BOT_TOKEN, CHANNEL_ID, OPENROUTER_API_KEY, PORT
from openrouter_cl import classify_intent, edit_current_post, get_structured_post, transcribe_audio

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# user_id -> готовый текст поста, ожидающий подтверждения
pending_posts: dict[int, str] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Опубликовать", callback_data="approve_post"),
        InlineKeyboardButton(text="❌ Отклонить",    callback_data="reject_post"),
    ]])


async def prepare_publication(user_id: int) -> None:
    archive = db.get_and_clear_thoughts(user_id)
    if not archive:
        await bot.send_message(user_id, "📭 Нет сохранённых мыслей для публикации.")
        return

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, get_structured_post, archive, OPENROUTER_API_KEY)

    post_text = result.get("post_text", "").strip()
    audit     = result.get("audit", "Аудит недоступен.").strip()

    if not post_text:
        await bot.send_message(user_id, f"⚠️ Не удалось сгенерировать пост.\n\n{audit}")
        return

    pending_posts[user_id] = post_text

    preview = (
        f"📋 АНАЛИЗ РИСКОВ ОТ GEMINI 3.5 FLASH:\n{audit}\n\n"
        f"--- 📝 ЧЕРНОВИК ПОСТА ---\n\n{post_text}"
    )
    await bot.send_message(user_id, preview, reply_markup=approval_keyboard())


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@dp.message(Command("start"))
async def handle_start(message: Message) -> None:
    await message.answer(
        "Бот работает ✅\n\n"
        "Отправь голосовое — Gemini транскрибирует и сохранит мысль.\n"
        "Скажи «опубликовать пост» — соберёт всё в готовый пост.\n"
        "/publish — то же самое командой."
    )


@dp.message(F.voice)
async def handle_voice(message: Message) -> None:
    if message.from_user.id != ALLOWED_USER_ID:
        print(f"[voice] отклонён user_id={message.from_user.id}")
        return

    user_id = message.from_user.id
    status_msg = await message.answer("🎙 Скачиваю аудио...")

    try:
        file_info = await bot.get_file(message.voice.file_id)
        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buf)
        audio_bytes = buf.getvalue()
        print(f"[voice] скачано {len(audio_bytes)} байт")

        await status_msg.edit_text("✍️ Транскрибирую...")

        loop = asyncio.get_running_loop()
        text_output = await loop.run_in_executor(
            None, transcribe_audio, audio_bytes, OPENROUTER_API_KEY
        )
        print(f"[voice] транскрипция: {text_output[:80]!r}")

        await status_msg.edit_text("🧠 Определяю намерение...")
        intent = await loop.run_in_executor(
            None, classify_intent, text_output, OPENROUTER_API_KEY
        )
        await status_msg.delete()

        if intent == "PUBLISH_POST":
            post_text = pending_posts.pop(user_id, None)
            if not post_text:
                await message.answer("⚠️ Нет готового черновика. Сначала сгенерируй пост командой /publish.")
                return
            await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
            await message.answer("✅ Пост опубликован в канале!")

        elif intent == "EDIT_POST":
            old_post = pending_posts.get(user_id)
            if not old_post:
                await message.answer("⚠️ Нет черновика для редактирования. Сначала сгенерируй пост командой /publish.")
                return
            notify = await message.answer("✏️ Вношу правки в черновик...")
            result = await loop.run_in_executor(
                None, edit_current_post, old_post, text_output, OPENROUTER_API_KEY
            )
            await notify.delete()

            post_text = result.get("post_text", "").strip()
            audit     = result.get("audit", "Аудит недоступен.").strip()

            if not post_text:
                await message.answer(f"⚠️ Не удалось отредактировать пост.\n\n{audit}")
                return

            pending_posts[user_id] = post_text
            preview = (
                f"📋 АУДИТ ПРАВОК ОТ GEMINI:\n{audit}\n\n"
                f"--- 📝 ОБНОВЛЁННЫЙ ЧЕРНОВИК ---\n\n{post_text}"
            )
            await message.answer(preview, reply_markup=approval_keyboard())

        elif intent == "SHOW_POST":
            post_text = pending_posts.get(user_id)
            if not post_text:
                await message.answer("📭 Черновика пока нет. Сгенерируй пост командой /publish.")
            else:
                await message.answer(
                    f"--- 📝 ТЕКУЩИЙ ЧЕРНОВИК ---\n\n{post_text}",
                    reply_markup=approval_keyboard(),
                )

        else:  # SAVE_THOUGHT
            db.add_thought(user_id, text_output)
            await message.answer(f"💾 Мысль сохранена:\n\n{text_output}")

    except Exception as e:
        print(f"[voice] ОШИБКА: {e}")
        traceback.print_exc()
        try:
            await status_msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await message.answer(f"❌ Ошибка: {e}")


@dp.message(F.text, F.forward_from_chat)
async def handle_forwarded_emoji(message: Message) -> None:
    """Извлекает custom_emoji_id из пересланных постов канала @perviy_stomatolog."""
    if message.from_user.id != ALLOWED_USER_ID:
        return

    fwd_chat = message.forward_from_chat
    if not fwd_chat or fwd_chat.username != "perviy_stomatolog":
        return

    if not message.entities:
        await message.answer("ℹ️ В пересланном посте нет entities с эмодзи.")
        return

    # Telegram использует UTF-16 offset/length — конвертируем корректно
    text_utf16 = message.text.encode("utf-16-le")
    saved: list[tuple[str, str]] = []

    for entity in message.entities:
        if entity.type != "custom_emoji" or not entity.custom_emoji_id:
            continue
        start = entity.offset * 2
        end   = (entity.offset + entity.length) * 2
        emoji_char = text_utf16[start:end].decode("utf-16-le")

        db.save_emoji(emoji_char, entity.custom_emoji_id)
        saved.append((emoji_char, entity.custom_emoji_id))
        print(f"[emoji] сохранён {emoji_char!r} → {entity.custom_emoji_id}")

    if not saved:
        await message.answer("ℹ️ Анимированных эмодзи в пересланном посте не найдено.")
        return

    lines = [f"✅ Эмодзи {char} сохранён с ID {eid}!" for char, eid in saved]
    await message.answer("\n".join(lines))


@dp.message(Command("publish"))
async def handle_publish(message: Message) -> None:
    if message.from_user.id != ALLOWED_USER_ID:
        return
    notify = await message.answer("🔄 Собираю архив и готовлю публикацию...")
    await prepare_publication(message.from_user.id)
    await notify.delete()


@dp.callback_query(F.data == "approve_post")
async def handle_approve(callback: CallbackQuery) -> None:
    user_id   = callback.from_user.id
    post_text = pending_posts.pop(user_id, None)

    if not post_text:
        await callback.answer("⚠️ Пост не найден в кэше.", show_alert=True)
        return

    await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ Пост опубликован в канале!")
    await callback.answer()


@dp.callback_query(F.data == "reject_post")
async def handle_reject(callback: CallbackQuery) -> None:
    pending_posts.pop(callback.from_user.id, None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Пост отклонён.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

async def on_startup(bot: Bot) -> None:
    db.init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    print(f"[startup] webhook установлен: {WEBHOOK_URL}")


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    print("[shutdown] webhook удалён")


async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="Бот работает")


def main() -> None:
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/", health_check)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    print(f"[main] запуск на порту {PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

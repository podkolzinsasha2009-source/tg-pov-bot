import asyncio
import io

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import BOT_TOKEN, ALLOWED_USER_ID, BASE_WEBHOOK_URL, PORT
from openrouter_cl import process_audio_to_post

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(F.voice)
async def handle_voice(message: Message) -> None:
    if message.from_user.id != ALLOWED_USER_ID:
        return

    status_msg = await message.answer("🎙 Скачиваю аудио...")

    file_info = await bot.get_file(message.voice.file_id)
    buf = io.BytesIO()
    await bot.download_file(file_info.file_path, destination=buf)
    audio_bytes = buf.getvalue()

    await status_msg.edit_text("📝 Gemini генерирует пост...")

    loop = asyncio.get_running_loop()
    post_text = await loop.run_in_executor(None, process_audio_to_post, audio_bytes)

    await message.answer(post_text, parse_mode="Markdown")
    await status_msg.delete()


async def on_startup(bot: Bot) -> None:
    await bot.set_webhook(WEBHOOK_URL)


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()


async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="Бот работает")


def main() -> None:
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/", health_check)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

import html
import logging
import os

from aiogram import Router, F
from aiogram.types import (
    Message,
    FSInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.filters import Command, CommandObject

import downloader
import pending
from config import cfg
from queue_manager import TaskQueue

logger = logging.getLogger(__name__)
router = Router(name="direct")
_ACTIONS = (
    ("mp4", "📹 Видео"),
    ("mp3", "🎵 Аудио (MP3)"),
    ("clip", "✂️ Клип 30 сек"),
)

def _offer_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=label,
                callback_data=f"dl|{action}|{pending.store(action, url)}",
            )
            for action, label in _ACTIONS
        ]]
    )
def setup_direct_handlers(task_queue: TaskQueue):

    @router.message(Command("start", "help"))
    async def cmd_start(message: Message):
        me = await message.bot.get_me()
        await message.answer(
            "Пришли ссылку на видео (YouTube / TikTok / Instagram / Pinterest) — "
            "я предложу кнопки: скачать видео, вытащить MP3 или вырезать первые 30 сек.\n\n"
            f"Также можно вызывать меня inline: наберите в любом чате "
            f"@{me.username} ссылка_на_видео, и появятся те же варианты."
        )

    @router.message(F.text.regexp(r"https?://\S+"))
    async def handle_link(message: Message):
        url = downloader.extract_url(message.text)
        if not url or not downloader.is_supported(url):
            return

        await message.reply(
            "Нашёл ссылку на видео -- что сделать?",
            reply_markup=_offer_keyboard(url),
        )

    @router.callback_query(F.data.startswith("dl|"))
    async def handle_offer_choice(callback: CallbackQuery):
        _, action, key = callback.data.split("|", 2)
        stored = pending.pop(key)
        if stored is None:
            await callback.answer("Кнопка устарела, пришлите ссылку ещё раз.", show_alert=True)
            return
        _, url = stored
        await callback.answer()

        status_msg = callback.message
        await status_msg.edit_text(
            f"⏳ В очереди... (сейчас в очереди: {task_queue.pending})"
        )

        async def job():
            if action == "mp4":
                result = await downloader.download_video(url)
            elif action == "mp3":
                result = await downloader.download_audio(url)
            else:
                result = await downloader.trim_clip(url, start_sec=0, duration_sec=30)
            try:
                size_mb = os.path.getsize(result.file_path) / (1024 * 1024)
                if size_mb > cfg.max_file_size_mb:
                    await status_msg.edit_text(
                        f"⚠️ Файл {size_mb:.1f} МБ превышает лимит Telegram Bot API "
                        f"({cfg.max_file_size_mb} МБ) для обычных ботов. "
                        f"Нужен self-hosted Bot API сервер для больших файлов."
                    )
                    return
                await status_msg.edit_text("⬆️ Загружаю в Telegram...")
                caption = html.escape(result.title)[:1024]
                if result.is_audio:
                    await status_msg.answer_audio(FSInputFile(result.file_path), caption=caption)
                else:
                    if action == "clip":
                        caption = f"{caption} (0:00-0:30)"[:1024]
                    await status_msg.answer_video(FSInputFile(result.file_path), caption=caption)
                await status_msg.delete()
            finally:
                downloader.cleanup(result)

        try:
            future = await task_queue.submit(job, description=f"{action}:{url}")
        except Exception:
            await status_msg.edit_text("🚧 Очередь загрузок переполнена, попробуйте чуть позже.")
            return

        try:
            await future
        except downloader.UnsupportedLinkError:
            await status_msg.edit_text("Платформа не поддерживается.")
        except downloader.DownloadError as e:
            await status_msg.edit_text(f"❌ Не удалось скачать: {e}", parse_mode=None)
        except Exception:
            logger.exception("Unexpected error processing %s (%s)", url, action)
            await status_msg.edit_text("❌ Непредвиденная ошибка при обработке ссылки.")

    @router.message(Command("debug"))
    async def cmd_debug(message: Message, command: CommandObject):
        if not cfg.admin_id or message.from_user.id != cfg.admin_id:
            return

        url = downloader.extract_url(command.args or "")
        if not url:
            await message.reply("Использование: /debug <ссылка>", parse_mode=None)
            return

        status = await message.reply("⏳ Гоняю yt-dlp в verbose-режиме, без скачивания файла...")
        log_text = await downloader.debug_extract(url)

        log_path = f"/tmp/ytdlp_debug_{message.message_id}.txt"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(log_text)

        await status.delete()
        await message.reply_document(
            FSInputFile(log_path, filename="ytdlp_debug.txt"),
            caption="Эквивалент `yt-dlp -vU <ссылка>`, без скачивания файла.",
            parse_mode=None,
        )
        os.remove(log_path)
    return router

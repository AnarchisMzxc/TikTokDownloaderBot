import html
import logging
import uuid
from collections import OrderedDict

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ChosenInlineResult,
    InputMediaVideo,
    InputMediaAudio,
    FSInputFile,
)

import downloader
from config import cfg
from queue_manager import TaskQueue

logger = logging.getLogger(__name__)

router = Router(name="inline")

ACTION_MP4 = "mp4"
ACTION_MP3 = "mp3"
ACTION_CLIP = "clip"

EMPTY_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[])
LOADING_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⏳ Загрузка…", callback_data="inline_wait")]]
)
_pending: OrderedDict[str, tuple[str, str]] = OrderedDict()
_PENDING_LIMIT = 1000


def _store_result(action: str, url: str) -> str:
    result_id = uuid.uuid4().hex
    _pending[result_id] = (action, url)
    while len(_pending) > _PENDING_LIMIT:
        _pending.popitem(last=False)
    return result_id


def _pop_result(result_id: str) -> tuple[str, str] | None:
    return _pending.pop(result_id, None)


def setup_inline_handlers(task_queue: TaskQueue, bot_username: str):

    @router.inline_query()
    async def handle_inline_query(inline_query: InlineQuery):
        url = downloader.extract_url(inline_query.query)
        if not url or not downloader.is_supported(url):
            await inline_query.answer(
                results=[],
                switch_pm_text="Вставьте ссылку на видео (YouTube/TikTok/Instagram/Pinterest)",
                switch_pm_parameter="help",
                cache_time=1,
                is_personal=True,
            )
            return

        results = [
            InlineQueryResultArticle(
                id=_store_result(ACTION_MP4, url),
                title="📹 Скачать MP4",
                description="Видео в максимальном качестве без водяных знаков",
                input_message_content=InputTextMessageContent(
                    message_text=f"⏳ Загружаю видео...\n{url}", parse_mode=None
                ),
                reply_markup=LOADING_KEYBOARD,
            ),
            InlineQueryResultArticle(
                id=_store_result(ACTION_MP3, url),
                title="🎵 Извлечь аудио (MP3/WAV)",
                description="Только звуковая дорожка",
                input_message_content=InputTextMessageContent(
                    message_text=f"⏳ Извлекаю аудио...\n{url}", parse_mode=None
                ),
                reply_markup=LOADING_KEYBOARD,
            ),
            InlineQueryResultArticle(
                id=_store_result(ACTION_CLIP, url),
                title="✂️ Вырезать 30 сек",
                description="Первые 30 секунд ролика",
                input_message_content=InputTextMessageContent(
                    message_text=f"⏳ Вырезаю клип...\n{url}", parse_mode=None
                ),
                reply_markup=LOADING_KEYBOARD,
            ),
        ]

        await inline_query.answer(results=results, cache_time=1, is_personal=True)

    @router.callback_query(F.data == "inline_wait")
    async def handle_wait_button(callback: CallbackQuery):
        await callback.answer("Ещё загружаю, подождите…", show_alert=False)

    @router.chosen_inline_result()
    async def handle_chosen_result(chosen: ChosenInlineResult):
        stored = _pop_result(chosen.result_id)
        if stored is None:
            logger.warning("Unknown inline result_id %s", chosen.result_id)
            return

        action, url = stored
        inline_message_id = chosen.inline_message_id
        bot = chosen.bot

        if not inline_message_id:
            logger.warning(
                "chosen_inline_result without inline_message_id — the result "
                "needs an inline keyboard (it has one) and inline feedback "
                "must be enabled via @BotFather (/setinlinefeedback)."
            )
            return

        async def job():
            try:
                if not cfg.effective_storage_chat_id:
                    await bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        text=(
                            "❌ Бот не настроен для inline-режима: задайте "
                            "STORAGE_CHAT_ID (или ADMIN_ID) в .env."
                        ),
                        parse_mode=None,
                        reply_markup=EMPTY_KEYBOARD,
                    )
                    return

                if action == ACTION_MP4:
                    result = await downloader.download_video(url)
                elif action == ACTION_MP3:
                    result = await downloader.download_audio(url)
                elif action == ACTION_CLIP:
                    result = await downloader.trim_clip(url, start_sec=0, duration_sec=30)
                else:
                    await bot.edit_message_text(
                        inline_message_id=inline_message_id,
                        text="❌ Неизвестное действие.",
                        parse_mode=None,
                        reply_markup=EMPTY_KEYBOARD,
                    )
                    return

                minted = None
                try:
                    caption = html.escape(result.title)[:1024]
                    if action == ACTION_CLIP:
                        caption = f"{html.escape(result.title)} (0:00-0:30)"[:1024]

                    if result.is_audio:
                        minted = await bot.send_audio(
                            chat_id=cfg.effective_storage_chat_id,
                            audio=FSInputFile(result.file_path),
                            caption=caption,
                        )
                        file_id = (minted.audio or minted.document).file_id
                        media = InputMediaAudio(media=file_id, caption=caption)
                    else:
                        minted = await bot.send_video(
                            chat_id=cfg.effective_storage_chat_id,
                            video=FSInputFile(result.file_path),
                            caption=caption,
                        )
                        file_id = (minted.video or minted.document).file_id
                        media = InputMediaVideo(media=file_id, caption=caption)

                    await bot.edit_message_media(
                        inline_message_id=inline_message_id,
                        media=media,
                        reply_markup=EMPTY_KEYBOARD,
                    )
                finally:
                    if minted is not None:
                        try:
                            await bot.delete_message(
                                chat_id=cfg.effective_storage_chat_id,
                                message_id=minted.message_id,
                            )
                        except Exception:
                            logger.debug("Could not delete minted storage message", exc_info=True)
                    downloader.cleanup(result)

            except downloader.UnsupportedLinkError:
                await bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text="❌ Платформа не поддерживается.",
                    parse_mode=None,
                    reply_markup=EMPTY_KEYBOARD,
                )
            except downloader.DownloadError as e:
                await bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text=f"❌ Не удалось скачать: {e}",
                    parse_mode=None,
                    reply_markup=EMPTY_KEYBOARD,
                )
            except Exception:
                logger.exception("Inline job failed for %s (%s)", url, action)
                await bot.edit_message_text(
                    inline_message_id=inline_message_id,
                    text="❌ Непредвиденная ошибка.",
                    parse_mode=None,
                    reply_markup=EMPTY_KEYBOARD,
                )

        try:
            await task_queue.submit(job, description=f"{action}:{url}")
        except Exception:
            await bot.edit_message_text(
                inline_message_id=inline_message_id,
                text="🚧 Очередь загрузок переполнена, попробуйте позже.",
                parse_mode=None,
                reply_markup=EMPTY_KEYBOARD,
            )

    return router

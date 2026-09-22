import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import cfg
from queue_manager import TaskQueue
from handlers.direct import setup_direct_handlers
from handlers.inline import setup_inline_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    task_queue = TaskQueue(max_workers=cfg.max_workers, max_size=cfg.queue_max_size)
    task_queue.start()

    me = await bot.get_me()
    logger.info("Starting as @%s", me.username)

    dp.include_router(setup_direct_handlers(task_queue))
    dp.include_router(setup_inline_handlers(task_queue, me.username))

    try:
        await dp.start_polling(bot)
    finally:
        await task_queue.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)
@dataclass
class DownloadTask:
    task_id: str
    coro_factory: Callable[[], Awaitable[None]]
    description: str = ""
    future: asyncio.Future = field(default=None, repr=False)
class TaskQueue:
    def __init__(self, max_workers: int = 3, max_size: int = 100):
        self._queue: asyncio.Queue[DownloadTask] = asyncio.Queue(maxsize=max_size)
        self._max_workers = max_workers
        self._workers: list[asyncio.Task] = []
        self._started = False
    def start(self):
        if self._started:
            return
        self._started = True
        for i in range(self._max_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        logger.info("TaskQueue started with %d workers", self._max_workers)
    async def stop(self):
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False
    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def submit(self, coro_factory: Callable[[], Awaitable[None]], description: str = "") -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        task = DownloadTask(
            task_id=str(uuid.uuid4()),
            coro_factory=coro_factory,
            description=description,
            future=future,
        )
        self._queue.put_nowait(task)
        return future

    async def _worker_loop(self, worker_id: int):
        logger.info("Worker %d started", worker_id)
        while True:
            task = await self._queue.get()
            try:
                logger.info("Worker %d picked up %s (%s)", worker_id, task.task_id, task.description)
                result = await task.coro_factory()
                if not task.future.done():
                    task.future.set_result(result)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("Task %s failed", task.task_id)
                if not task.future.done():
                    task.future.set_exception(e)
            finally:
                self._queue.task_done()

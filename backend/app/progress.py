import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from contextvars import ContextVar
from time import monotonic
from typing import Any
from uuid import uuid4

from app.models import ChatResponse

_sink: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar("progress_sink", default=None)
logger = logging.getLogger(__name__)


def report_progress(stage: str, message: str, **details: Any) -> None:
    sink = _sink.get()
    if sink is not None:
        sink({"type": "progress", "stage": stage, "message": message, **details})


async def stream_chat(
    run: Callable[[], Awaitable[ChatResponse]], timeout: float = 120,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    started = monotonic()
    request_id = str(uuid4())
    sequence = 0

    def publish(event: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        queue.put_nowait({
            **event, "request_id": request_id, "sequence": sequence,
            "elapsed_ms": round((monotonic() - started) * 1000),
        })

    async def produce() -> None:
        token = _sink.set(publish)
        try:
            report_progress("accepted", "요청을 접수했습니다.")
            result = await asyncio.wait_for(run(), timeout=timeout)
            publish({"type": "result", "result": result.model_dump(mode="json")})
        except TimeoutError:
            publish({"type": "error", "message": "처리 시간이 초과되었습니다. 다시 시도해 주세요."})
        except Exception as error:
            logger.exception(
                "Chat request %s failed (%s)", request_id, type(error).__name__, exc_info=False,
            )
            publish({"type": "error", "message": "처리 중 오류가 발생했습니다. 서버 연결과 모델 설정을 확인해 주세요."})
        finally:
            _sink.reset(token)

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                yield json.dumps({"type": "heartbeat"}) + "\n"
                continue
            yield json.dumps(event, ensure_ascii=False) + "\n"
            if event["type"] in ("result", "error"):
                break
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
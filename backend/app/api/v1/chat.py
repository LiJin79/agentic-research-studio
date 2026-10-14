import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.dependencies import ChatServiceDependency
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, service: ChatServiceDependency) -> ChatResponse:
    """执行一次非流式 Agentic RAG 问答。"""
    return await service.ask(
        session_id=payload.session_id,
        message=payload.message,
        use_web_search=payload.use_web_search,
        request_id=payload.request_id,
        model_id=payload.model_id,
    )


@router.post("/stream")
async def stream_chat(payload: ChatRequest, service: ChatServiceDependency) -> StreamingResponse:
    """通过 Server-Sent Events 持续返回状态、文本块和完成事件。"""

    async def event_source() -> AsyncIterator[str]:
        """有界队列传递事件，空闲时发心跳，断开连接则取消整个运行。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)

        async def produce() -> None:
            """生产者执行 Agent，背压由队列容量限制。"""
            execution = service.stream(
                session_id=payload.session_id,
                message=payload.message,
                use_web_search=payload.use_web_search,
                request_id=payload.request_id,
                model_id=payload.model_id,
            )
            try:
                async for item in execution:
                    await queue.put(item)
            finally:
                # 若取消发生在 queue.put 的背压等待，也要关闭正在 yield 的服务生成器。
                await execution.aclose()
                if not asyncio.current_task().cancelling():
                    await queue.put(None)

        task = asyncio.create_task(produce())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                data = json.dumps(item["data"], ensure_ascii=False)
                yield f"event: {item['event']}\ndata: {data}\n\n"
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

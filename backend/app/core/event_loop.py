import asyncio


def selector_loop_factory(use_subprocess: bool = False):
    """Uvicorn 显式事件循环入口，Windows psycopg 需要 SelectorEventLoop。"""
    return asyncio.SelectorEventLoop()

import asyncio

from app.db.checkpointer import close_checkpointer, create_checkpointer_context


async def main() -> None:
    """检查 Checkpoint 连接池能否初始化，不输出连接字符串或密钥。"""
    try:
        async with create_checkpointer_context():
            print("checkpoint_pool_ready", type(asyncio.get_running_loop()).__name__)
    finally:
        await close_checkpointer()


if __name__ == "__main__":
    from app.main import configure_windows_event_loop

    configure_windows_event_loop()
    asyncio.run(main())

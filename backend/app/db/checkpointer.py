import asyncio
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None
_init_lock = asyncio.Lock()


def checkpoint_conninfo() -> str:
    """本机明确使用 IPv4 并设置连接超时，容器继续通过服务名解析。"""
    value = get_settings().langgraph_postgres_dsn
    options = {"connect_timeout": 5}
    if conninfo_to_dict(value).get("host") == "localhost":
        options["hostaddr"] = "127.0.0.1"
    return make_conninfo(value, **options)


@asynccontextmanager
async def create_checkpointer_context():
    """复用进程级连接池，整个图运行期间保持 saver 可用。"""
    global _pool, _saver
    if _saver is None:
        async with _init_lock:
            if _saver is None:
                pool = AsyncConnectionPool(
                    conninfo=checkpoint_conninfo(),
                    min_size=1,
                    max_size=5,
                    open=False,
                    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                )
                try:
                    await pool.open()
                    await pool.wait(timeout=15)
                except BaseException:
                    await pool.close()
                    raise
                _pool, _saver = pool, AsyncPostgresSaver(pool)
    yield _saver


async def close_checkpointer() -> None:
    """应用退出时释放 checkpoint 连接，下一次启动建立新池。"""
    global _pool, _saver, _init_lock
    if _pool is not None:
        await _pool.close()
    _pool, _saver = None, None
    _init_lock = asyncio.Lock()


async def setup_checkpointer_schema() -> None:
    """迁移进程使用短连接准备表，不依赖 API 的进程级连接池。"""
    async with AsyncPostgresSaver.from_conn_string(checkpoint_conninfo()) as saver:
        await saver.setup()

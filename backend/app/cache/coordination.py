import hashlib
import json
import logging
import uuid
from contextlib import asynccontextmanager

from app.cache.redis import get_redis_client
from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededError

logger = logging.getLogger(__name__)
RATE_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""
UNLOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
 return redis.call('DEL', KEYS[1])
end
return 0
"""


class ConversationBusyError(RuntimeError):
    """同一会话已有运行或删除任务，调用方应稍后重试。"""


@asynccontextmanager
async def conversation_lock(session_id: uuid.UUID):
    """Redis 原子租约跨 API 进程串行化会话；租约长于整次运行截止时间。"""
    redis = get_redis_client()
    key, token = f"lock:chat:{session_id}", str(uuid.uuid4())
    if not await redis.set(key, token, nx=True, ex=get_settings().chat_timeout_seconds + 60):
        raise ConversationBusyError("该会话正在执行，请先完成或取消当前请求")
    try:
        yield
    finally:
        await redis.eval(UNLOCK_SCRIPT, 1, key, token)


async def enforce_rate_limit(session_id: uuid.UUID) -> None:
    """Lua 将计数与过期设置合为原子操作，避免产生永不过期的限流键。"""
    count = await get_redis_client().eval(RATE_SCRIPT, 1, f"rate:chat:{session_id}", 60)
    if count > get_settings().chat_rate_limit_per_minute:
        raise RateLimitExceededError("请求过于频繁，请一分钟后重试")


def search_cache_key(kind: str, query: str) -> str:
    """缓存键包含模型版本和检索限制，配置改变不会命中旧向量结果。"""
    settings = get_settings()
    value = json.dumps(
        [
            query.strip(),
            settings.embedding_fingerprint,
            settings.retrieval_top_k,
            settings.retrieval_min_score,
            settings.web_search_max_results,
            settings.web_search_provider,
            settings.bocha_base_url,
        ],
        ensure_ascii=False,
    )
    return f"search:{kind}:{hashlib.sha256(value.encode()).hexdigest()}"


async def cached_search(key: str, fetch):
    """缓存短期搜索资料；缓存故障只跳过缓存，不伪造外部搜索结果。"""
    redis = get_redis_client()
    try:
        existing = await redis.get(key)
        if existing:
            return json.loads(existing)
    except Exception:
        logger.warning("search_cache_read_failed")
    result = await fetch()
    try:
        await redis.set(
            key, json.dumps(result, ensure_ascii=False), ex=get_settings().search_cache_seconds
        )
    except Exception:
        logger.warning("search_cache_write_failed")
    return result

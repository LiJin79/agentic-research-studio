"""避免回答节点读到了历史，但校验或修订又把有效记忆删掉。"""

import asyncio
import json

from app.agents.graph import build_agent_graph
from app.llm.factory import MockLLMClient


class MemoryLLM(MockLLMClient):
    """要求各节点看到同一段用户历史，模拟真实验收发现的记忆丢失。"""

    def __init__(self, revise=False):
        """可额外触发一次修订，检查修订节点同样保留历史信息。"""
        self.revise, self.verifications = revise, 0

    async def generate(self, messages, *, json_mode=False):
        """只有包含历史中的真实代号才允许校验通过。"""
        prompt = messages[-1].content
        if "ROUTE_DECISION" in prompt:
            return '{"route":"direct","reason":"会话记忆"}'
        if "VERIFY_ANSWER" in prompt:
            self.verifications += 1
            assert '"role": "user"' in prompt and "MEM-4827" in prompt
            return json.dumps(
                {
                    "supported": not self.revise or self.verifications > 1,
                    "feedback": "调整措辞" if self.verifications == 1 else "ok",
                }
            )
        return await super().generate(messages, json_mode=json_mode)

    async def stream(self, messages):
        """原回答和修订都须依据用户历史，而不是模型凭空记住。"""
        prompt = messages[-1].content
        assert '"role": "user"' in prompt and "MEM-4827" in prompt
        yield "你的测试代号是 MEM-4827。"


def test_verifier_and_revision_keep_user_provided_memory():
    """正常和被要求修订两条路径都不能丢掉已持久化的用户信息。"""

    async def run():
        for revise in [False, True]:
            graph = build_agent_graph(llm=MemoryLLM(revise))
            result = await graph.ainvoke(
                {
                    "question": "刚才我的测试代号是什么？",
                    "history": [
                        {"role": "user", "content": "我的测试代号是 MEM-4827"},
                        {"role": "assistant", "content": "已记住"},
                    ],
                    "use_web_search": False,
                    "context": [],
                    "sources": [],
                    "trace": [],
                    "revision_count": 0,
                }
            )
            assert "MEM-4827" in result["answer"]
            assert result["answer_supported"]
            assert result["revision_count"] == int(revise)

    asyncio.run(run())

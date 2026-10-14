"""办公文档技能的输入和模型大纲，所有数量与文字长度都有明确边界。"""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ArtifactRequest(BaseModel):
    """以一条已完成的助手消息为资料，生成可编辑的 Word 或 PowerPoint。"""

    message_id: uuid.UUID
    format: Literal["docx", "pptx"]
    title: str = Field(default="研究报告", min_length=1, max_length=100)


class SlideOutline(BaseModel):
    """单页只保留有限要点；完整解释放在演讲者备注，避免文字溢出。"""

    title: str = Field(min_length=1, max_length=40)
    bullets: list[Annotated[str, Field(min_length=1, max_length=85)]] = Field(
        min_length=1, max_length=4
    )
    notes: str = Field(default="", max_length=2000)


class PresentationOutline(BaseModel):
    """模型负责把已有回答组织成演示大纲，不引入新的事实或搜索结果。"""

    slides: list[SlideOutline] = Field(min_length=1, max_length=12)

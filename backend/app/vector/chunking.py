from dataclasses import dataclass


@dataclass(slots=True)
class TextChunk:
    """一段将被向量化的文本及其在原文中的顺序。"""

    index: int
    content: str


def split_text(text: str, *, chunk_size: int, overlap: int) -> list[TextChunk]:
    """按字符窗口切分文本，并保留重叠区域避免语义在边界处断裂。"""
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []
    if overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")

    chunks: list[TextChunk] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(TextChunk(index=len(chunks), content=cleaned[start:end]))
        if end == len(cleaned):
            break
        start = end - overlap
    return chunks

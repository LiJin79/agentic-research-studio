import pytest
from app.vector.chunking import split_text
from app.vector.parsing import UnsupportedDocumentError, extract_text


def test_split_text_preserves_overlap_and_order() -> None:
    """相邻块应保留配置的重叠文本，并拥有连续索引。"""
    chunks = split_text("abcdefghij", chunk_size=6, overlap=2)

    assert [chunk.index for chunk in chunks] == [0, 1]
    assert [chunk.content for chunk in chunks] == ["abcdef", "efghij"]


def test_extract_text_supports_json_and_markdown() -> None:
    """常见文本格式应转换成可切分的 Unicode 字符串。"""
    markdown = extract_text("note.md", "# 标题\n内容".encode())
    json_text = extract_text("data.json", b'{"name": "knowledge base"}')

    assert "标题" in markdown
    assert "knowledge base" in json_text


def test_extract_text_rejects_unknown_extension() -> None:
    """不允许的文件类型必须在进入数据库和 Qdrant 前失败。"""
    with pytest.raises(UnsupportedDocumentError):
        extract_text("program.exe", b"not a document")

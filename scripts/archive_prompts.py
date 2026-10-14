"""生成中英提示词的版本化 Markdown 档案；不包含用户消息、API Key 或运行数据。"""

import hashlib
import json
from pathlib import Path

from app.agents import prompts, prompts_en


def main() -> None:
    """归档完整模板并保存 SHA256，便于学习、审阅及后续追踪变更。"""
    root = Path(__file__).resolve().parents[1] / "docs" / "prompts" / "2026-10-13-tools-v1"
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"version": root.name, "runtime_language": "zh", "files": {}}
    for language, module in [("zh", prompts), ("en", prompts_en)]:
        parts = [f"# Prompt Archive ({language})\n\nVersion: {root.name}\n"]
        for name, value in vars(module).items():
            if name.isupper() and isinstance(value, str):
                parts.append(f"\n## {name}\n\n```text\n{value.strip()}\n```\n")
        content = "".join(parts)
        target = root / f"prompts.{language}.md"
        target.write_text(content, encoding="utf-8")
        manifest["files"][target.name] = hashlib.sha256(content.encode()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Archived Chinese and English prompts: {root}")


if __name__ == "__main__":
    main()

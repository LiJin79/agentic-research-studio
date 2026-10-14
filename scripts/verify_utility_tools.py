"""一次性工具探测：不调用大模型，失败只记录，不重试外部供应商。"""

import asyncio
import json
from pathlib import Path

from app.agents.tools.utility import calculate_csv, read_webpage, search_github, search_papers


async def main() -> None:
    """验证实际网页、仓库和论文网络链路，报告不包含凭据或完整来源内容。"""
    report = []
    probes = [
        ("read_webpage", lambda: read_webpage("https://fastapi.tiangolo.com/")),
        ("search_github", lambda: search_github("repo:fastapi/fastapi")),
        ("search_papers", lambda: search_papers("retrieval augmented generation")),
    ]
    for name, run in probes:
        try:
            values = await run()
            report.append({"tool": name, "status": "passed" if values else "empty",
                           "result_count": len(values)})
        except Exception as exc:
            report.append({"tool": name, "status": "failed",
                           "error": (str(exc) or type(exc).__name__)[:150]})
    result = calculate_csv(b"region,sales\nA,10\nA,20\nB,7\n", "sum", "sales", "region")
    report.append({"tool": "analyze_table", "status": "passed", "results": result["results"]})
    target = Path(__file__).resolve().parents[1] / "evaluation" / "utility-tools-live.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

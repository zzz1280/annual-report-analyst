"""运行 QA 评测：
- 引用有效率 grounding_rate（规则）：回答中 (p.N) 引用的页码必须全部落在检索证据页范围内
- 回答正确率（LLM-as-judge）：0/1/2 分

用法:
    python scripts/run_eval.py <pdf_stem> [--limit 20] [--include-unreviewed]
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from report_analyst.config import settings  # noqa: E402
from report_analyst.index import HybridIndex  # noqa: E402
from report_analyst.llm import chat_json  # noqa: E402
from report_analyst.parse import load_doc  # noqa: E402
from report_analyst.qa import answer  # noqa: E402

JUDGE_PROMPT = """你是评测裁判。对比"参考答案"与"学生答案"，判断学生答案是否正确且完整。
只输出 JSON：{{"score": 0, "reason": "一句话理由"}}
score 取值：0=错误或编造，1=部分正确，2=正确且完整。

问题: {q}
参考答案: {ref}
学生答案: {ans}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-unreviewed", action="store_true")
    args = ap.parse_args()

    eval_path = settings.eval_dir / f"qa_{args.stem}.jsonl"
    items = [json.loads(x) for x in eval_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not args.include_unreviewed:
        items = [x for x in items if x.get("reviewed")]
    if args.limit:
        items = items[: args.limit]
    assert items, "评测集为空：先运行 scripts/build_eval.py 并复核。"

    d = settings.parsed_dir / args.stem
    index = HybridIndex.load(d)
    assert index is not None, "未找到索引：先运行 python -m report_analyst parse <pdf>"
    load_doc(d)  # 校验解析产物存在

    results = []
    for it in items:
        r = answer(index, it["question"])
        cited = set(r["cited_pages"])
        grounded = bool(cited) and cited <= set(r["evidence_pages"])
        judge = chat_json([{"role": "user", "content": JUDGE_PROMPT.format(
            q=it["question"], ref=it["reference_answer"], ans=r["answer"][:1500])}])
        results.append({"id": it["id"], "question": it["question"],
                        "cited_pages": r["cited_pages"], "grounded": grounded,
                        "score": judge.get("score", 0), "reason": judge.get("reason", "")})
        print(f"[{len(results)}/{len(items)}] {it['question'][:40]} "
              f"grounded={grounded} score={judge.get('score')}")

    n = len(results)
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "n": n,
        "grounding_rate": round(sum(r["grounded"] for r in results) / n, 4) if n else 0,
        "accuracy_score2": round(sum(r["score"] == 2 for r in results) / n, 4) if n else 0,
        "accuracy_score_ge1": round(sum(r["score"] >= 1 for r in results) / n, 4) if n else 0,
    }
    out_dir = settings.eval_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{args.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps({"summary": summary, "detail": results},
                                   ensure_ascii=False, indent=1), encoding="utf-8")

    table = Table(title="QA 评测结果")
    table.add_column("指标")
    table.add_column("数值", justify="right")
    for k, v in summary.items():
        if k != "run_at":
            table.add_row(k, str(v))
    Console().print(table)
    print(f"详情 → {out_file}")


if __name__ == "__main__":
    main()

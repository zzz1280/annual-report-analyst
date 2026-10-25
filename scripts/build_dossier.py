"""生成 agent-in-the-loop 评测所需的检索卷宗（不调用任何 API）。

对每份年报的每道评测题：用项目的真实检索代码（HybridIndex.search, k=8）取证据块，
写出一个"卷宗"文件（问题 + top-4 证据块全文 + 页码），供答题代理只凭卷宗作答；
同时导出题目文件（不含参考答案，防泄漏）与证据页范围（供 grounding 机械校验）。

用法:
    python scripts/build_dossier.py [stem ...]   # 缺省处理全部 5 份
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from report_analyst.index import HybridIndex, best_excerpt  # noqa: E402
from report_analyst.parse import load_doc  # noqa: E402

ALL_STEMS = ["600519_2023", "000002_2023", "000333_2023", "600036_2023", "300750_2023"]
TOP_K_SHOW = 4      # 展示给答题者的证据块数（检索仍按 k=8 算证据页范围）
SHOW_CHARS = 600    # 每块展示字符数


def main() -> None:
    stems = sys.argv[1:] or ALL_STEMS
    for stem in stems:
        doc = load_doc(f"data/parsed/{stem}")
        idx = HybridIndex.load(f"data/parsed/{stem}")
        assert idx is not None, f"{stem} 缺少索引"
        items = [json.loads(l) for l in open(f"data/eval/qa_{stem}.jsonl", encoding="utf-8")]

        # 题目文件（不含参考答案，避免答题代理看到标准答案）
        with open(f"data/eval/questions_{stem}.jsonl", "w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps({"id": it["id"], "question": it["question"]},
                                   ensure_ascii=False) + "\n")

        evidence = {}
        with open(f"data/eval/dossier_{stem}.txt", "w", encoding="utf-8") as f:
            for it in items:
                hits = idx.search(it["question"], k=8)
                ev_pages = sorted({p for h in hits for p in range(h["page_start"], h["page_end"] + 1)})
                evidence[it["id"]] = ev_pages
                f.write(f"\n{'=' * 72}\n题目 id: {it['id']}\n问题: {it['question']}\n")
                f.write(f"检索材料（按相关度排序，页码为年报页码；共检索到 {len(hits)} 块，展示前 {TOP_K_SHOW} 块）:\n")
                for h in hits[:TOP_K_SHOW]:
                    f.write(f"--- 第{h['page_start']}页 [{h['section'][:24]}] ---\n")
                    f.write(best_excerpt(h["text"], it["question"], SHOW_CHARS) + "\n")

        json.dump(evidence, open(f"data/eval/evidence_{stem}.json", "w", encoding="utf-8"),
                  ensure_ascii=False)
        print(f"{stem}: {len(items)} 题，卷宗与题目文件已生成")


if __name__ == "__main__":
    main()

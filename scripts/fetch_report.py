"""从巨潮资讯网（cninfo）下载上市公司年度报告 PDF。

用法:
    python scripts/fetch_report.py 600519 [--year 2023] [--out data/raw]

实现说明: cninfo 的全文搜索接口排序不稳定且对深市代码带空格的关键词失效，
因此只用它取股票的 orgId；年报列表改由结构化的 hisAnnouncement/query 接口
按"年度报告"分类 + 发布年份精确查询。
"""

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0"}
SEARCH_URL = ("http://www.cninfo.com.cn/new/fulltextSearch/full?searchkey={kw}"
              "&sdate=&edate=&isfulltext=false&sortName=nothing&sortType=desc&pageNum=1")
QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"


def _strip_tags(s: str) -> str:
    return re.sub(r"</?em>", "", s)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as resp:
        return json.loads(resp.read())


def _post_form(url: str, form: dict) -> dict:
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_org_id(code: str) -> str | None:
    kw = urllib.parse.quote(f"{code}年度报告")
    anns = _get_json(SEARCH_URL.format(kw=kw)).get("announcements") or []
    for a in anns:
        if a.get("secCode") == code and a.get("orgId"):
            return a["orgId"]
    return None


def find_announcement(code: str, year: str) -> tuple[str, str] | None:
    """返回 (公告标题, adjunctUrl)。全文 = 标题含"{年份}年年度报告"且非摘要/英文版。"""
    org_id = _get_org_id(code)
    if not org_id:
        return None
    column = "sse" if org_id.startswith("gssh") else "szse"
    form = {
        "pageNum": "1", "pageSize": "30", "column": column, "tabName": "fulltext",
        "stock": f"{code},{org_id}", "category": "category_ndbg_szsh",
        # 年报于次年发布，区间放宽到后两年以兼容晚披露
        "seDate": f"{int(year) + 1}-01-01~{int(year) + 2}-12-31",
        "isHLtitle": "true",
    }
    data = _post_form(QUERY_URL, form)
    for a in data.get("announcements") or []:
        title = _strip_tags(a.get("announcementTitle", ""))
        if a.get("adjunctType") == "PDF" and a.get("adjunctUrl") \
                and f"{year}年年度报告" in title \
                and not any(bad in title for bad in ("摘要", "英文", "已取消")):
            return title, a["adjunctUrl"]
    return None


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as f:
        while chunk := resp.read(1 << 16):
            f.write(chunk)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("code", help="股票代码，如 600519")
    ap.add_argument("--year", default="2023")
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args()

    found = find_announcement(args.code, args.year)
    if not found:
        raise SystemExit(f"未找到 {args.code} {args.year} 年度报告的全文公告")
    title, adjunct = found
    full_url = f"http://static.cninfo.com.cn/{adjunct}"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{args.code}_{args.year}.pdf"
    print(f"公告: {title}\n下载: {full_url} -> {dest}")
    download(full_url, dest)
    print(f"完成: {dest.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

"""数字审计的回归测试：真实 LLM 曾把 74,734,071,550.75 抄成 747,340,71550.75，此错误类必须被拦截。"""

from report_analyst.report import audit_numbers

SRC = ["营业收入 147,693,604,994.14 元，同比 19.01%；归属于上市公司股东的净利润 74,734,071,550.75 元；2023年"]


def test_clean_report_passes():
    md = "营业收入 1,476.94 亿元，同比 +19.01% (p.5)。归母净利润 747.34 亿元 (p.5)。"
    r = audit_numbers(md, SRC)
    assert r["bad_grouping"] == []
    assert r["untraced"] == [], "亿元换算与四舍五入必须可溯源"


def test_comma_transposition_caught():
    md = "净利润 747,340,71550.75 元 (p.5)。"
    r = audit_numbers(md, SRC)
    assert r["bad_grouping"] == ["747,340,71550.75"]


def test_untraceable_number_flagged():
    md = "其他收入 8,888,888,888.88 元 (p.9)。"
    r = audit_numbers(md, SRC)
    assert "8,888,888,888.88" in r["untraced"]


def test_citation_pages_not_audited():
    md = "详见 (p.999) 与 (p.123456)。"
    r = audit_numbers(md, SRC)
    assert r["untraced"] == [] and r["bad_grouping"] == []

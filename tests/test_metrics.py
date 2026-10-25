"""指标计算是纯 Python，必须 100% 单测覆盖——这是"LLM 只读数、本地计算"设计的底气。"""

from report_analyst.metrics import compute_metrics


def test_yoy_and_margin():
    figures = {
        "营业收入": {"current": 120.0, "prior": 100.0},
        "归属于上市公司股东的净利润": {"current": 10.0, "prior": 12.0},
    }
    m = compute_metrics(figures)
    assert m["营业收入同比"]["value"] == 0.2
    assert abs(m["归母净利润同比"]["value"] - (-1 / 6)) < 1e-9
    assert abs(m["归母净利率"]["value"] - (10 / 120)) < 1e-9


def test_debt_ratio_estimate():
    figures = {
        "总资产": {"current": 200.0},
        "归属于上市公司股东的净资产": {"current": 100.0},
    }
    m = compute_metrics(figures)
    assert m["资产负债率(估算)"]["value"] == 0.5
    assert "note" in m["资产负债率(估算)"]


def test_debt_ratio_exact_when_total_liability_present():
    figures = {"总资产": {"current": 200.0}, "总负债": {"current": 90.0}}
    m = compute_metrics(figures)
    assert m["资产负债率"]["value"] == 0.45
    assert "资产负债率(估算)" not in m


def test_cash_flow_ratio():
    figures = {
        "经营活动产生的现金流量净额": {"current": 8.0},
        "归属于上市公司股东的净利润": {"current": 10.0},
    }
    m = compute_metrics(figures)
    assert m["净现比"]["value"] == 0.8


def test_prior_zero_is_skipped():
    figures = {"营业收入": {"current": 120.0, "prior": 0}}
    assert "营业收入同比" not in compute_metrics(figures)


def test_missing_items_are_skipped():
    assert compute_metrics({}) == {}

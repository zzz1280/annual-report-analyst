"""分块规则的回归测试：真实数据评测中修过的三个 bug（标题误判/页眉杂讯/报表归属）永不复发。"""

from report_analyst.index import chunk_doc

LONG_ITEM = "一、本公司董事会、监事会及董事、监事、高级管理人员保证年度报告内容真实、准确、完整"


def _doc():
    return {
        "source": "test.pdf",
        "n_pages": 3,
        "pages": [
            {"page": 1,
             "tables": [[["科目", "金额"], ["营业收入", "100"], ["净利润", "50"]]],
             "text": f"2023年年度报告\n1 / 3\n第三节 管理层讨论与分析\n一、主营业务分析\n公司主要业务是卖酒。\n{LONG_ITEM}"},
            {"page": 2,
             "tables": [[["项目", "期末"], ["资产总计", "171"]], [["单行表"]]],
             "text": "2023年年度报告\n2 / 3\n母公司资产负债表\n正文内容。"},
            {"page": 3,
             "tables": [],
             "text": "2023年年度报告\n3 / 3\n第三节 管理层讨论与分析\n续文。"},
        ],
    }


def test_furniture_and_page_numbers_removed():
    chunks = chunk_doc(_doc())
    assert chunks
    for c in chunks:
        assert "2023年年度报告" not in c["text"], "页眉杂讯必须被剔除"
        assert "1 / 3" not in c["text"] and "3 / 3" not in c["text"], "页码行必须被剔除"


def test_long_numbered_line_is_body_not_heading():
    chunks = chunk_doc(_doc())
    host = [c for c in chunks if LONG_ITEM in c["text"]]
    assert len(host) == 1, "长句编号项应留在正文中"
    assert host[0]["section"] == "一、主营业务分析"
    assert all(not c["section"].startswith("一、本公司") for c in chunks), "长句不能被误判为章节标题"


def test_statement_title_becomes_section_and_prefixes_table():
    chunks = chunk_doc(_doc())
    body = [c for c in chunks if "正文内容。" in c["text"]]
    assert body and body[0]["section"] == "母公司资产负债表"
    tbl = [c for c in chunks if "资产总计" in c["text"]]
    assert tbl and tbl[0]["text"].startswith("[母公司资产负债表]"), "表格分块必须带报表归属前缀"


def test_single_row_table_skipped():
    chunks = chunk_doc(_doc())
    assert not any("单行表" in c["text"] for c in chunks)


def test_pages_preserved():
    chunks = chunk_doc(_doc())
    tbl = next(c for c in chunks if "资产总计" in c["text"])
    assert (tbl["page_start"], tbl["page_end"]) == (2, 2)

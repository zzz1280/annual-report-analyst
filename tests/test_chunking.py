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


def test_long_table_split_into_row_groups():
    """超长表格必须按行分组切块且表头随每块重复——防止关键行被下游截断埋没。"""
    tbl = [["科目", "金额"]] + [[f"项目{i:02d}", "5" * 50] for i in range(24)]
    doc = {"source": "t.pdf", "n_pages": 1,
           "pages": [{"page": 1, "text": "母公司资产负债表\n", "tables": [tbl]}]}
    chunks = chunk_doc(doc)
    tbl_chunks = [c for c in chunks if c["text"].startswith("[母公司资产负债表]")]
    assert len(tbl_chunks) >= 2, "约 1400 字的表格应被切成多块"
    for c in tbl_chunks:
        assert "科目 | 金额" in c["text"], "表头必须随每块重复"
        assert len(c["text"]) <= 1400, "分块不应远超上限"
        assert (c["page_start"], c["page_end"]) == (1, 1)


def test_short_table_stays_single_chunk():
    tbl = [["科目", "金额"], ["营业收入", "100"], ["净利润", "50"]]
    doc = {"source": "t.pdf", "n_pages": 1,
           "pages": [{"page": 1, "text": "", "tables": [tbl]}]}
    chunks = chunk_doc(doc)
    assert len(chunks) == 1 and "营业收入 | 100" in chunks[0]["text"]


def test_statement_scope_tagging():
    """报表标题为分块打持久口径标签：合并/母公司。"""
    doc = {"source": "t.pdf", "n_pages": 1,
           "pages": [{"page": 1, "text": "合并资产负债表\n资产总计 100\n母公司资产负债表\n资产总计 50",
                      "tables": []}]}
    chunks = chunk_doc(doc)
    assert chunks[0]["scope"] == "合并"
    assert chunks[1]["scope"] == "母公司"


def test_headline_scope_is_consolidated():
    """"主要会计数据"是合并口径——茅台 021 类错误的病根就在这里被误标。"""
    doc = {"source": "t.pdf", "n_pages": 1,
           "pages": [{"page": 1, "text": "七、近三年主要会计数据和财务指标\n(一) 主要会计数据\n经营活动产生的现金流量净额 66,593,247,721.09",
                      "tables": []}]}
    chunks = chunk_doc(doc)
    assert all(c["scope"] == "合并" for c in chunks if "现金流量净额" in c["text"])


def test_best_excerpt_finds_relevant_window():
    from report_analyst.index import best_excerpt

    text = "无关的开头内容。" + "甲" * 800 + "研发投入合计 621,507,535.87 元，占营业收入比例 0.42%。" + "乙" * 800
    ex = best_excerpt(text, "本期研发投入合计是多少", 400)
    assert "621,507,535.87" in ex, "截取窗口必须落在查询相关内容上，而不是头部"
    assert best_excerpt("短文本", "短文本", 400) == "短文本"
    assert best_excerpt("没有命中词的长文本" + "丙" * 900, "完全无关的查询词", 100).startswith("没有命中词")

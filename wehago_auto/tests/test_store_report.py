import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import store  # noqa: E402
from report import render, summarize  # noqa: E402


def r(sq, name, kind, state, total=1100):
    return {"sq_sbook": sq, "거래처": name, "일자": "07-01", "구분": "법인", "유형": kind,
            "차변계정": "(판)소모품비", "합계": total, "전표상태코드": state}


def test_store_history_and_report():
    s = {}
    store.update(s, "A사", [r(1, "(주)마트", "일반", "2"), r(2, "(주)마트", "일반", "2"),
                           r(3, "마트", "카과", "1"), r(4, "카페", "카과", "2")])
    store.update(s, "B사", [r(1, "카페", "일반", "2")])
    hist = store.past_types(s, "A사", processed_states={"2"}, exclude=["3"])
    assert hist[store.normalize("마트")]["일반"] == 2 and "카과" not in hist[store.normalize("마트")]
    store.apply_results(s, "A사", {3: {"유형": "일반"}})
    summary = summarize(s)
    mart = [x for x in summary["A사"] if "마트" in x["거래처"]][0]
    assert mart["판정"] == "일반" and mart["일반 건수"] == 3 and mart["일반 금액"] == 3300
    assert summary["B사"][0]["판정"] == "일반"
    assert "A사" in render(summary) and "<script" not in render(summary)

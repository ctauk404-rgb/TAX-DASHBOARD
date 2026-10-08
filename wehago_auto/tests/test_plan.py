import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codes  # noqa: E402
from classifier import DEFAULT_SETTINGS, Rule  # noqa: E402
from plan import Accounts, build_changes  # noqa: E402

LIST = [
    {"sq_sbook": 1, "nm_trade": "동네분식", "ty_biz": 3, "ty_mth2": "57", "ty_jungstat": 1,
     "nm_acctit_cha": "(판)복리후생비", "cd_acctit_cha": "81100", "mn_vat": 100.0},
    {"sq_sbook": 2, "nm_trade": "(주)카카오페이", "ty_biz": 2, "ty_mth2": "57", "ty_jungstat": 1,
     "nm_acctit_cha": "(판)소모품비", "cd_acctit_cha": "83000", "mn_vat": 100.0},
    {"sq_sbook": 3, "nm_trade": "모르는가게", "ty_biz": 1, "ty_mth2": "57", "ty_jungstat": 1,
     "nm_acctit_cha": "미추천", "cd_acctit_cha": None, "mn_vat": 100.0},
    {"sq_sbook": 4, "nm_trade": "전송된가게", "ty_biz": 3, "ty_mth2": "57", "ty_jungstat": 2,
     "nm_acctit_cha": "(판)복리후생비", "cd_acctit_cha": "81100", "mn_vat": 100.0},
]
CODEHELP = [{"cd_acctit": "83100", "nm_acctit": "지급수수료"},
            {"cd_acctit": "53100", "nm_acctit": "지급수수료"}]


def test_account_codes():
    acc = Accounts(LIST, CODEHELP)
    assert acc.code("(판)복리후생비") == "81100"
    assert acc.code("(판)지급수수료") == "83100"   # 코드도움 + (판)=8xxxx
    assert acc.code("지급수수료") is None          # 판관/제조 구분 불가 → 모름
    assert acc.code("82200") == "82200"


def test_build_changes():
    c, _ = codes.merge_grid_labels([])
    rows = [codes.to_row(d, c) for d in LIST]
    rules = [Rule("", "카카오페이", "", "(판)지급수수료", "")]
    changes, skipped = build_changes(rows, "", rules, DEFAULT_SETTINGS,
                                     Accounts(LIST, CODEHELP), states={"1"})
    got = {(ch["sq_sbook"], ch["field"], ch["typed"]) for ch in changes}
    assert got == {(1, "ty_mth2", "3"), (2, "cd_acctit_cha", "83100")}
    assert skipped == {"검토 필요": 1, "전표상태 제외": 1}

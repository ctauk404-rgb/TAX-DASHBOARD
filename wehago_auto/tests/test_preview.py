import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codes  # noqa: E402
from classifier import DEFAULT_SETTINGS, Rule  # noqa: E402
from preview import build_groups, render  # noqa: E402


def raw(nm_trade, ty_biz, ty_mth, acct, vat=100.0):
    ty_mth = {2: "57", 3: "3"}[ty_mth]
    return {"nm_trade": nm_trade, "ty_biz": ty_biz, "ty_mth2": ty_mth, "nm_acctit_cha": acct,
            "mn_vat": vat, "mn_total": 1100.0, "ty_jungstat": 1, "bizcond": "", "bizcate": ""}


def test_codes_and_grid_label_override():
    c, confirmed = codes.merge_grid_labels([{"columns": [
        {"fieldName": "ty_jungstat", "values": [1, 2], "labels": ["확정가능", "미추천"]}]}])
    assert confirmed == {"ty_jungstat"}
    row = codes.to_row(raw("동네분식", 3, 2, "(판)복리후생비"), c)
    assert (row["구분"], row["유형"], row["전표상태"]) == ("간이", "카과", "확정가능")


def test_preview_groups_and_changes():
    c, _ = codes.merge_grid_labels([])
    rows = [codes.to_row(r, c) for r in [
        raw("동네분식", 3, 2, "(판)복리후생비"),          # 간이인데 카과 → 일반으로 변경
        raw("( 주 ) 카카오페이", 2, 2, "(판)소모품비"),    # 규칙으로 계정 변경
        raw("주식회사 카카오페이", 2, 2, "(판)소모품비"),
        raw("모르는가게", 1, 2, "미추천"),                 # 계정 미정 → 검토
    ]]
    rules = [Rule("", "카카오페이", "", "(판)지급수수료", "")]
    groups = {g["거래처"]: g for g in build_groups(rows, "", rules, DEFAULT_SETTINGS)}
    assert groups["동네분식"]["변경"] == 1 and "일반(1)" in groups["동네분식"]["제안유형"]
    assert groups["( 주 ) 카카오페이"]["건수"] == 2 and groups["( 주 ) 카카오페이"]["변경"] == 2
    assert groups["모르는가게"]["검토"]
    html = render("테스트", rows, list(groups.values()), "note")
    assert "<script" not in html and "카카오페이" in html

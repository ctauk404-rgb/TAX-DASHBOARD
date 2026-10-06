import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classifier import Rule, classify, group_by_merchant, normalize  # noqa: E402


def row(거래처, 구분="법인", 세액="354", 업태="", 종목="", 차변계정="(판)소모품비", 전표상태="확정가능"):
    return dict(거래처=거래처, 구분=구분, 세액=세액, 업태=업태, 종목=종목,
                차변계정=차변계정, 전표상태=전표상태)


RULES = [
    Rule("", "카카오페이", "", "(판)지급수수료", ""),
    Rule("팔각도", "카카오페이", "", "(판)복리후생비", ""),
    Rule("", "", "주유", "(판)차량유지비", ""),
    Rule("", "거래처접대식당", "", "(판)접대비", ""),
]


def test_normalize_ignores_corp_marks_and_spaces():
    assert normalize("( 주 ) 비에스케이코퍼레이션") == normalize("비에스케이코퍼레이션")
    assert normalize("주식회사 카카오페이") == normalize("(주)카카오페이")


def test_simple_and_exempt_merchants_are_general():
    assert classify(row("아윤의원 강남", 구분="면세"), "", RULES).vat_type == "일반"
    assert classify(row("동네분식", 구분="간이"), "", RULES).vat_type == "일반"


def test_client_rule_beats_common_rule():
    d = classify(row("주식회사 카카오페이"), "팔각도 거제아주점", RULES)
    assert d.account == "(판)복리후생비"
    d = classify(row("주식회사 카카오페이"), "다른수임처", RULES)
    assert d.account == "(판)지급수수료"


def test_industry_rule_and_deductible_default():
    d = classify(row("OO에너지", 업태="소매", 종목="주유소"), "", RULES)
    assert (d.account, d.vat_type, d.review) == ("(판)차량유지비", "카과", False)


def test_entertainment_is_non_deductible():
    assert classify(row("거래처접대식당"), "", RULES).vat_type == "일반"


def test_keeps_wehago_recommendation_when_no_rule():
    d = classify(row("(주)케이지이니시스"), "", RULES)
    assert d.account == "(판)소모품비" and "위하고 추천" in d.reason


def test_unrecommended_row_needs_review():
    d = classify(row("아윤의원 강남", 구분="일반", 차변계정="미추천", 전표상태="미추천"), "", RULES)
    assert d.account == "" and d.review


def test_zero_tax_and_suspicious_industry():
    assert classify(row("어딘가", 세액="0"), "", RULES).vat_type == "일반"
    d = classify(row("주식회사 티머니모빌리티", 업태="운수업", 종목="택시"), "", RULES)
    assert d.vat_type == "일반" and d.review


def test_group_by_merchant():
    groups = group_by_merchant([row("(주)비에스케이"), row("( 주 ) 비에스케이"), row("나이스정보통신(주)")])
    assert sorted(len(g) for g in groups.values()) == [1, 2]

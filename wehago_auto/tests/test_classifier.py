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


def test_learned_history_per_client():
    from learn import build_profile

    def past(name, kind, n, 종목="주유소", 카드=""):
        return [dict(거래처=name, 유형=kind, 차변계정="(판)차량유지비", 종목=종목, 카드=카드)] * n

    # 화물차 수임처: 주유 카과 / 승용차 수임처: 주유 일반 — 같은 주유소라도 수임처마다 다르게
    truck = build_profile(past("OO주유소", "카과", 5))
    car = build_profile(past("OO주유소", "일반", 4))
    r = row("(주)OO주유소", 업태="소매", 종목="주유소")
    assert classify(r, "", RULES, history=truck).vat_type == "카과"
    d = classify(r, "", RULES, history=car)
    assert d.vat_type == "일반" and "학습(같은 거래처" in d.reason

    # 처음 보는 주유소 → 이 수임처의 같은 업종(주유소) 기록을 따름
    d = classify(row("새주유소", 종목="주유소"), "", RULES, history=car)
    assert d.vat_type == "일반" and "같은 업종" in d.reason

    # 같은 수임처에서 섞여 있으면 검토
    mixed = build_profile(past("OO주유소", "카과", 3) + past("OO주유소", "일반", 3))
    d = classify(r, "", RULES, history=mixed)
    assert d.review and "과거 혼재" in d.reason

    # 차량별로 카드를 나눠 쓰면 카드 기준이 우선
    by_card = build_profile(past("OO주유소", "카과", 3, 카드="1111") + past("OO주유소", "일반", 3, 카드="2222"))
    assert classify(dict(r, 카드="1111"), "", RULES, history=by_card).vat_type == "카과"
    assert classify(dict(r, 카드="2222"), "", RULES, history=by_card).vat_type == "일반"

    # 간이·면세는 학습보다 우선 (항상 일반)
    assert classify(row("동네주유", 구분="간이", 종목="주유소"), "", RULES, history=truck).vat_type == "일반"

"""신용카드 매입 전표 분류 규칙 엔진.

위하고 화면과 무관한 순수 로직이다. 위하고 표의 한 줄(가맹점 거래 1건)을 받아
'유형'과 '차변계정'을 정하고, 그렇게 정한 근거와 검토 필요 여부를 돌려준다.
"""

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).parent

DEFAULT_SETTINGS = {
    # 유형 이름 → 위하고 유형 코드(ty_mth2). 유형 칸에 이 숫자를 입력한다.
    "type_codes": {"카과": "57", "일반": "3"},
    # 자동 입력할 전표상태 코드 (비어 있으면 실행할 때 물어봄)
    "editable_states": [],
    # 조회 기간 시작일 (MM.DD 는 올해, YYYY.MM.DD 도 가능). 상반기 전표를 함께 읽어 과거 판단에 씀
    "period_from": "01.01",
    # 자동화에 쓸 브라우저: "chrome" 또는 "edge"
    "browser": "chrome",
    # 매입세액 공제 받는 카드 매입의 유형 (더존 매입매출 유형 '카과')
    "deductible_type": "카과",
    # 공제 받지 않는 경우의 유형
    "non_deductible_type": "일반",
    # 위하고 '구분' 칸이 이 값이면 무조건 일반 (사용자 지정 규칙)
    "always_general_kinds": ["간이", "면세"],
    # 이 계정이면 매입세액 불공제 → 일반
    "non_deductible_accounts": ["접대비", "기업업무추진비"],
    # 업태/종목에 이 단어가 있으면 불공제 가능성 → 일반 + 검토 표시
    "non_deductible_industry_keywords": [
        "항공", "여객", "택시", "고속버스", "시외버스", "철도",
        "목욕", "이발", "미용",
    ],
}

_CORP_MARKS = re.compile(r"주식회사|유한회사|\(주\)|\(유\)|㈜")


def normalize(name):
    """'( 주 ) 비에스케이' 와 '비에스케이' 를 같은 이름으로 본다."""
    s = re.sub(r"\s+", "", name or "")
    s = _CORP_MARKS.sub("", s)
    return s.lower()


def parse_amount(text):
    s = str(text or "").replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


@dataclass
class Rule:
    client: str     # 수임처 (빈칸 = 모든 수임처 공통)
    merchant: str   # 가맹점(거래처)명에 포함된 문자열
    industry: str   # 업태/종목에 포함된 문자열
    account: str    # 차변계정
    vat_type: str   # 유형 (빈칸 = 자동 판단)
    memo: str = ""

    def matches(self, client, row):
        if self.client and normalize(self.client) not in normalize(client):
            return False
        if not self.merchant and not self.industry:
            return False
        if self.merchant and normalize(self.merchant) not in normalize(row.get("거래처")):
            return False
        if self.industry:
            industry = f"{row.get('업태', '')} {row.get('종목', '')}"
            if self.industry not in industry:
                return False
        return True

    @property
    def rank(self):
        """작을수록 우선. 수임처 전용 > 공통, 가맹점 지정 > 업종 지정."""
        return (0 if self.merchant else 2) + (0 if self.client else 1)


@dataclass
class Decision:
    vat_type: str
    account: str   # 빈칸이면 계정을 정하지 못한 것 (건드리지 않음)
    reason: str
    review: bool   # True 면 사람이 꼭 봐야 하는 건


def load_rules(path=BASE_DIR / "rules.csv"):
    rules = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rules.append(Rule(
                client=(r.get("수임처") or "").strip(),
                merchant=(r.get("가맹점") or "").strip(),
                industry=(r.get("업종") or "").strip(),
                account=(r.get("차변계정") or "").strip(),
                vat_type=(r.get("유형") or "").strip(),
                memo=(r.get("메모") or "").strip(),
            ))
    return rules


def load_settings(path=BASE_DIR / "settings.json"):
    settings = dict(DEFAULT_SETTINGS)
    if Path(path).exists():
        with open(path, encoding="utf-8") as f:
            settings.update(json.load(f))
    return settings


def past_general(history, row):
    """같은 거래처의 과거(처리된) 전표가 주로 '일반' 이면 그 건수, 아니면 0."""
    if not history:
        return 0
    counts = history.get(normalize(row.get("거래처")))
    if not counts:
        return 0
    general = counts.get(DEFAULT_SETTINGS["non_deductible_type"], 0)
    return general if general * 2 >= sum(counts.values()) else 0


def find_rule(client, row, rules):
    hits = [r for r in rules if r.matches(client, row)]
    return min(hits, key=lambda r: r.rank) if hits else None


def classify(row, client, rules, settings=DEFAULT_SETTINGS, history=None):
    """위하고 표의 한 줄을 분류한다.

    row 키: 거래처, 구분, 업태, 종목, 공급가액, 세액, 차변계정, 유형, 전표상태
    """
    reasons = []
    review = False

    # 1) 차변계정: 규칙 > 위하고 추천값 > 미정
    rule = find_rule(client, row, rules)
    current = (row.get("차변계정") or "").strip()
    if rule and rule.account:
        account = rule.account
        reasons.append(f"규칙: {rule.merchant or rule.industry}")
    elif current and current != "미추천" and row.get("전표상태") != "미추천":
        account = current
        reasons.append("위하고 추천 유지")
    else:
        account = ""
        reasons.append("계정 미정")
        review = True

    # 2) 유형
    kind = (row.get("구분") or "").strip()
    industry = f"{row.get('업태', '')} {row.get('종목', '')}"
    deductible = settings["deductible_type"]
    general = settings["non_deductible_type"]

    if kind in settings["always_general_kinds"]:
        vat_type = general
        reasons.append(f"{kind} 가맹점")
    elif rule and rule.vat_type:
        vat_type = rule.vat_type
    elif past_general(history, row):
        vat_type = general
        reasons.append(f"과거 전표 일반 {past_general(history, row)}건")
    elif any(a in account for a in settings["non_deductible_accounts"]):
        vat_type = general
        reasons.append("불공제 계정")
    elif str(row.get("세액") or "").strip() != "" and parse_amount(row.get("세액")) == 0:
        vat_type = general
        reasons.append("세액 0원")
    elif any(k in industry for k in settings["non_deductible_industry_keywords"]):
        vat_type = general
        reasons.append("불공제 업종 의심")
        review = True
    else:
        vat_type = deductible

    return Decision(vat_type=vat_type, account=account,
                    reason=", ".join(reasons), review=review)


def group_by_merchant(rows):
    """거래처(가맹점)별로 묶는다. 같은 가맹점은 같은 분류를 받는다."""
    groups = {}
    for row in rows:
        groups.setdefault(normalize(row.get("거래처")), []).append(row)
    return groups

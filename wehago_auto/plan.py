"""분류 결과 → 위하고에 입력할 변경 목록."""

import re

from classifier import classify

PREFIX_DIGIT = {"(판)": "8", "(제)": "5", "(도)": "6", "(분)": "7"}


class Accounts:
    """계정 이름 → 계정 코드. 목록 데이터의 (이름, 코드) 쌍과 위하고 계정 코드도움을 함께 쓴다."""

    def __init__(self, list_rows=(), codehelp=()):
        self.pairs = {}
        for d in list_rows:
            name, code = d.get("nm_acctit_cha"), d.get("cd_acctit_cha")
            if name and code and name != "미추천":
                self.pairs.setdefault(name, str(code))
        self.codehelp = [(str(c.get("cd_acctit") or ""), str(c.get("nm_acctit") or ""))
                         for c in codehelp if c.get("cd_acctit")]

    def code(self, name):
        name = (name or "").strip()
        if not name:
            return None
        if re.fullmatch(r"\d{3,6}", name):
            return name
        if name in self.pairs:
            return self.pairs[name]
        m = re.match(r"^(\([^)]*\))\s*(.+)$", name)
        prefix, bare = (m.group(1), m.group(2)) if m else ("", name)
        hits = [c for c, n in self.codehelp if n in (name, bare)]
        if prefix in PREFIX_DIGIT:
            hits = [c for c in hits if c.startswith(PREFIX_DIGIT[prefix])] or hits
        return hits[0] if len(hits) == 1 else None


def build_changes(rows, client, rules, settings, accounts, states, history=None):
    """rows: codes.to_row 결과. states: 자동 입력할 전표상태 코드 집합.

    돌려주는 값: (변경 목록, 건너뛴 사유별 건수)
    """
    changes, skipped = [], {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for r in rows:
        if r["전표상태코드"] not in states:
            skip("전표상태 제외")
            continue
        d = classify(r, client, rules, settings, history)
        if d.review:
            skip("검토 필요")
            continue
        row_changes = []
        type_code = settings["type_codes"].get(d.vat_type)
        if not type_code:
            skip(f"유형 코드 모름({d.vat_type})")
            continue
        if r["유형코드"] != type_code:
            row_changes.append(("ty_mth2", "유형", type_code, r["유형"], d.vat_type))
        acct_code = accounts.code(d.account)
        if not acct_code:
            skip("계정 코드 모름")
        elif r["계정코드"] != acct_code:
            row_changes.append(("cd_acctit_cha", "차변계정", acct_code, r["차변계정"], d.account))
        for field, label, code, before, after in row_changes:
            changes.append({"sq_sbook": r["sq_sbook"], "거래처": r["거래처"], "field": field,
                            "칸": label, "typed": code, "expect": code,
                            "전": before, "후": after, "근거": d.reason})
        if not row_changes:
            skip("이미 맞음")
    return changes, skipped

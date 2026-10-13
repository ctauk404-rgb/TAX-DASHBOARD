"""수임처별 과거 카드전표 학습.

같은 상호라도 수임처마다 공제 여부가 다르다 (예: 주유소 — 화물차·9인승 이상이면 카과,
승용차면 일반). 그래서 학습은 항상 '수임처 안에서만' 한다. 우선순위:

  1. 같은 카드 + 같은 거래처      (차량별로 카드를 나눠 쓰는 경우)
  2. 같은 거래처
  3. 같은 카드 + 같은 업종(종목)  (처음 보는 주유소라도 그 카드의 주유가 카과였으면 카과)
  4. 같은 업종(종목)

어느 단계든 과거 건수가 min_count 이상이고 한쪽이 share 이상이면 그 유형을 따른다.
건수는 충분한데 섞여 있으면(예: 화물차·승용차를 같은 카드로 주유) '혼재' 로 검토 표시한다.
"""

from collections import Counter

from classifier import normalize

LEVELS = [("card_merchant", "같은 카드·거래처"), ("merchant", "같은 거래처"),
          ("card_industry", "같은 카드·업종"), ("industry", "같은 업종")]


def industry_key(r):
    return normalize(r.get("종목") or r.get("업태") or "")


def keys(r):
    m, ind, card = normalize(r.get("거래처")), industry_key(r), str(r.get("카드") or "").strip()
    return {
        "card_merchant": (card, m) if card and m else None,
        "merchant": m or None,
        "card_industry": (card, ind) if card and ind else None,
        "industry": ind or None,
    }


def build_profile(records):
    """records: 확정(처리)된 과거 전표들 (store 의 값). 단계별로 유형·계정 건수를 센다."""
    profile = {level: {} for level, _ in LEVELS}
    for r in records:
        for level, key in keys(r).items():
            if key is None:
                continue
            slot = profile[level].setdefault(key, {"types": Counter(), "accounts": Counter()})
            slot["types"][r.get("유형", "")] += 1
            if r.get("차변계정") and r["차변계정"] != "미추천":
                slot["accounts"][r["차변계정"]] += 1
    return profile


def _majority(counter, min_count, share):
    total = sum(counter.values())
    if total < min_count:
        return None, total
    value, n = counter.most_common(1)[0]
    return (value if n / total >= share else "혼재"), total


def decide(profile, row, min_count=1, share=0.8):
    """돌려주는 값: {'유형': 값|'혼재'|None, '계정': 값|None, '근거': 설명}"""
    out = {"유형": None, "계정": None, "근거": ""}
    if not profile:
        return out
    k = keys(row)
    for level, label in LEVELS:
        slot = profile[level].get(k[level]) if k[level] is not None else None
        if not slot:
            continue
        if out["유형"] is None:
            value, total = _majority(slot["types"], min_count, share)
            if value:
                t = slot["types"]
                out["유형"] = value
                out["근거"] = f"학습({label}: " + ", ".join(f"{a} {b}" for a, b in t.most_common()) + ")"
        if out["계정"] is None and level in ("card_merchant", "merchant"):
            value, _ = _majority(slot["accounts"], min_count, share)
            if value and value != "혼재":
                out["계정"] = value
        if out["유형"] is not None and out["계정"] is not None:
            break
    return out


def summary(profile):
    merchants = profile.get("merchant", {})
    mixed = sum(1 for s in merchants.values() if _majority(s["types"], 2, 0.8)[0] == "혼재")
    return f"거래처 {len(merchants)}곳 · 업종 {len(profile.get('industry', {}))}종 학습 (혼재 거래처 {mixed}곳)"

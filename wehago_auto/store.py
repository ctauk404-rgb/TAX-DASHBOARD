"""수임처별 카드 매입 기록 (PC 에만 저장: data/기록.json).

위하고에서 목록을 읽을 때마다 건별 최신 상태(거래처, 일자, 유형, 차변계정, 합계, 전표상태)를
쌓아 둔다. 두 가지에 쓴다.
- 과거 전표 기준 판단: 이미 처리(전송)된 같은 거래처 전표가 '일반' 이면 이번에도 일반
- 최종 현황표: 수임처별 · 거래처별 일반/카과 구분 (report.py)
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from classifier import normalize, parse_amount

STORE_PATH = Path(__file__).parent / "data" / "기록.json"


def load(path=STORE_PATH):
    if Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {}


def save(store, path=STORE_PATH):
    Path(path).parent.mkdir(exist_ok=True)
    Path(path).write_text(json.dumps(store, ensure_ascii=False, indent=0), encoding="utf-8")


def update(store, client, rows):
    """rows: codes.to_row 결과. 같은 sq_sbook 은 최신 값으로 덮어쓴다."""
    book = store.setdefault(client, {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for r in rows:
        if r.get("sq_sbook") is None:
            continue
        book[str(r["sq_sbook"])] = {
            "거래처": r["거래처"], "일자": r.get("일자", ""), "구분": r.get("구분", ""),
            "유형": r["유형"], "차변계정": r["차변계정"], "합계": parse_amount(r.get("합계")),
            "전표상태코드": r["전표상태코드"], "갱신": now,
        }
    return store


def apply_results(store, client, results):
    """자동 입력 결과(sq → {'유형': .., '차변계정': ..}) 반영."""
    book = store.get(client, {})
    for sq, values in results.items():
        if str(sq) in book:
            book[str(sq)].update(values)


def past_types(store, client, processed_states, exclude=()):
    """이미 처리된 전표(processed_states)의 거래처별 유형 건수. exclude 는 이번에 고칠 건."""
    out = {}
    exclude = {str(s) for s in exclude}
    for sq, r in store.get(client, {}).items():
        if sq in exclude or r["전표상태코드"] not in processed_states:
            continue
        out.setdefault(normalize(r["거래처"]), Counter())[r["유형"]] += 1
    return out

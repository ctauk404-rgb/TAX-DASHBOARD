import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from site_recon import _header_only, masked  # noqa: E402


def test_masked_hides_values():
    m = masked({"list": [{"storeNm": "홍길동상회", "amt": 12000, "dt": "2026-10-01"}], "total": 1})
    assert m == {"list": ["len=1", {"storeNm": "str(5)", "amt": "int", "dt": "date"}], "total": "int"}


def test_header_only():
    rows = [["홍길동상회 카드매출", None], ["일자", "가맹점명", "금액"], ["2026-10-01", "김밥천국", 5000]]
    out = _header_only(rows)
    assert out[1] == ["(항목 이름)", "일자", "가맹점명", "금액"]
    assert "홍길동상회" not in str(out) and "김밥천국" not in str(out)

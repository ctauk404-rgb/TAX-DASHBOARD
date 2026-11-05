import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "samples"))

from openpyxl import load_workbook  # noqa: E402

from pl_report import build_reports, entity_type, expense_items, find_keys, review_flags  # noqa: E402
from sample_statements import CORP, PERSON  # noqa: E402


def test_keys_and_type():
    keys = find_keys(CORP["lines"])
    assert [k for k in ("매출액", "매출원가", "판매비와관리비", "영업이익", "세전이익", "법인세등", "당기순이익")
            if k in keys] == ["매출액", "매출원가", "판매비와관리비", "영업이익", "세전이익", "법인세등", "당기순이익"]
    assert entity_type(CORP["lines"]) == "법인" and entity_type(PERSON["lines"]) == "개인"
    assert len(expense_items(CORP["lines"], keys)) == 8


def test_flags():
    items = {(f["항목"], f["중요도"]) for f in review_flags(PERSON)}
    assert ("영업이익", "높음") in items and ("매출액", "중간") in items and ("수선비", "중간") in items
    corp = {f["항목"] for f in review_flags(CORP)}
    assert "지급수수료" in corp and "접대비(기업업무추진비)" in corp


def test_build(tmp_path):
    paths, internal, flags = build_reports([CORP, PERSON], tmp_path, tmp_path / "h.json")
    wb = load_workbook(paths[0])
    assert wb.sheetnames == ["요약", "손익계산서", "월별추이"]
    assert wb["손익계산서"]["D5"].value == "=B5-C5"
    assert "검토" not in " ".join(wb.sheetnames)  # 업체용에는 검토 메모 없음
    assert load_workbook(internal).sheetnames == ["수임처요약", "검토항목"]

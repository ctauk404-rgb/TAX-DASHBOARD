"""월별 손익 보고서 (엑셀).

입력: 수임처별 손익계산서 줄 목록 (위하고에서 읽은 값을 정리한 것)
    {"수임처": "팔각도", "연월": "2026-10",
     "lines": [{"계정": "Ⅰ.매출액", "level": 0, "당월": 1, "전월": 1, "전년동월": 1, "누계": 1, "전년누계": 1}, ...]}

출력
- 업체용  손익보고_{수임처}_{연월}.xlsx : 요약 / 손익계산서 / 월별추이  (업체에 그대로 보낼 수 있게 검토 메모 없음)
- 내부용  손익검토_{연월}.xlsx         : 수임처 요약 + 자동 검토 항목 (업체에 보내지 않음)
금액 칸은 위하고 값, 증감·증감률·이익률은 엑셀 수식이라 숫자를 고치면 같이 바뀐다.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HISTORY_PATH = Path(__file__).parent / "data" / "손익기록.json"

FONT = "맑은 고딕"
F = Font(name=FONT, size=10)
F_BOLD = Font(name=FONT, size=10, bold=True)
F_TITLE = Font(name=FONT, size=14, bold=True)
F_NOTE = Font(name=FONT, size=9, color="666666")
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
FILL_HEAD = PatternFill("solid", fgColor="44546A")
FILL_TOTAL = PatternFill("solid", fgColor="EEF2F7")
FILL_FLAG = PatternFill("solid", fgColor="FFF4E5")
THIN = Side(style="thin", color="D0D5DD")
BORDER = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
WON = '#,##0;(#,##0);"-"'
PCT = '0.0%;(0.0%);"-"'

PERIODS = ["당월", "전월", "전년동월", "누계", "전년누계"]

# 손익계산서 주요 합계 줄 (위하고 줄 이름을 정규화해서 찾는다)
KEY_ITEMS = [
    ("매출액", lambda n: n in ("매출액", "매출", "수익", "영업수익")),
    ("매출원가", lambda n: n in ("매출원가", "영업원가")),
    ("매출총이익", lambda n: n.startswith("매출총")),
    ("판매비와관리비", lambda n: n.startswith("판매비와") or n == "판관비"),
    ("영업이익", lambda n: n.startswith("영업이익") or n.startswith("영업손")),
    ("영업외수익", lambda n: n == "영업외수익"),
    ("영업외비용", lambda n: n == "영업외비용"),
    ("세전이익", lambda n: "차감전" in n),
    ("법인세등", lambda n: n in ("법인세등", "법인세비용", "소득세등", "소득세비용")),
    ("당기순이익", lambda n: n.startswith("당기순")),
]
KEY_LABEL = {"세전이익": "세전이익", "법인세등": "법인세(소득세)등"}


def normalize_name(name):
    s = re.sub(r"^\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|[IVX]+\.|\d+\.|\(\d+\)|[가-하]\.)\s*", "", str(name or ""))
    s = re.sub(r"[\s\.\(\)（）·]", "", s)
    return s.replace("（", "").replace("）", "")


def find_keys(lines):
    """주요 항목 → lines 의 위치. 앞에서부터 처음 맞는 줄."""
    found = {}
    for i, line in enumerate(lines):
        n = normalize_name(line["계정"])
        for key, match in KEY_ITEMS:
            if key not in found and match(n):
                found[key] = i
                break
    return found


def entity_type(lines):
    names = " ".join(normalize_name(l["계정"]) for l in lines)
    return "법인" if "법인세" in names else "개인"


def expense_items(lines, keys):
    """판매비와관리비 세부 항목 (판관비 줄 다음부터 영업이익 줄 전까지)."""
    start, end = keys.get("판매비와관리비"), keys.get("영업이익")
    if start is None or end is None or end <= start:
        return []
    return [i for i in range(start + 1, end) if lines[i].get("level", 1) > lines[start].get("level", 0)]


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def key_values(statement):
    lines, keys = statement["lines"], find_keys(statement["lines"])
    return {k: {p: num(lines[i].get(p)) for p in PERIODS} for k, i in keys.items()}


# ---- 월별 추이 기록 -----------------------------------------------------------
def load_history(path=HISTORY_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}


def save_history(history, path=HISTORY_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")


def remember(history, statement):
    vals = key_values(statement)
    history.setdefault(statement["수임처"], {})[statement["연월"]] = {k: v["당월"] for k, v in vals.items()}
    return history


# ---- 엑셀 공통 ----------------------------------------------------------------
def _cell(ws, row, col, value=None, font=F, fmt=None, fill=None, align=None, border=True):
    c = ws.cell(row=row, column=col, value=value)
    c.font = font
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if align:
        c.alignment = Alignment(horizontal=align, vertical="center")
    if border:
        c.border = BORDER
    return c


def _header(ws, row, titles, start_col=1):
    for j, t in enumerate(titles):
        _cell(ws, row, start_col + j, t, F_HEAD, fill=FILL_HEAD, align="center")


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ---- 업체용 보고서 -------------------------------------------------------------
STATEMENT_COLS = ["계정과목", "당월", "전월", "전월 대비", "증감률", "전년 동월", "전년 대비", "증감률",
                  "누계", "전년 누계"]


def write_statement_sheet(ws, statement):
    """손익계산서 시트. 돌려주는 값: 원래 줄 번호 → 엑셀 행 번호."""
    ws.title = "손익계산서"
    ym = statement["연월"]
    _cell(ws, 1, 1, f"{statement['수임처']} 손익계산서 ({ym})", F_TITLE, border=False)
    _cell(ws, 2, 1, "단위: 원 · 자료: 위하고 손익계산서", F_NOTE, border=False)
    _header(ws, 4, STATEMENT_COLS)
    keys = set(find_keys(statement["lines"]).values())
    rows = {}
    for i, line in enumerate(statement["lines"]):
        r = 5 + i
        rows[i] = r
        total = i in keys
        font, fill = (F_BOLD, FILL_TOTAL) if total else (F, None)
        name = _cell(ws, r, 1, str(line["계정"]).strip(), font, fill=fill)
        name.alignment = Alignment(indent=0 if total else min(int(line.get("level", 1)), 3) + 1)
        for col, p in ((2, "당월"), (3, "전월"), (6, "전년동월"), (9, "누계"), (10, "전년누계")):
            _cell(ws, r, col, num(line.get(p)), font, WON, fill)
        _cell(ws, r, 4, f"=B{r}-C{r}", font, WON, fill)
        _cell(ws, r, 5, f'=IF(C{r}=0,"",(B{r}-C{r})/ABS(C{r}))', font, PCT, fill)
        _cell(ws, r, 7, f"=B{r}-F{r}", font, WON, fill)
        _cell(ws, r, 8, f'=IF(F{r}=0,"",(B{r}-F{r})/ABS(F{r}))', font, PCT, fill)
    _widths(ws, [28, 15, 15, 14, 9, 15, 14, 9, 16, 16])
    ws.freeze_panes = "B5"
    return rows


def write_summary_sheet(ws, statement, rows):
    lines = statement["lines"]
    keys = find_keys(lines)
    ref = lambda key, col: f"=손익계산서!{col}{rows[keys[key]]}" if key in keys else 0
    ws.title = "요약"
    _cell(ws, 1, 1, f"{statement['수임처']} 월별 손익 보고서", F_TITLE, border=False)
    _cell(ws, 2, 1, f"대상 월: {statement['연월']} · {entity_type(lines)} · 단위: 원", F_NOTE, border=False)

    _header(ws, 4, ["항목", "당월", "전월", "전월 대비", "증감률", "전년 동월", "전년 대비", "누계"])
    r = 5
    key_rows = {}
    for key, _ in KEY_ITEMS:
        if key not in keys:
            continue
        bold = key in ("매출액", "영업이익", "당기순이익")
        font, fill = (F_BOLD, FILL_TOTAL) if bold else (F, None)
        _cell(ws, r, 1, KEY_LABEL.get(key, key), font, fill=fill)
        for col, src in ((2, "B"), (3, "C"), (6, "F"), (8, "I")):
            _cell(ws, r, col, ref(key, src), font, WON, fill)
        _cell(ws, r, 4, f"=B{r}-C{r}", font, WON, fill)
        _cell(ws, r, 5, f'=IF(C{r}=0,"",(B{r}-C{r})/ABS(C{r}))', font, PCT, fill)
        _cell(ws, r, 7, f"=B{r}-F{r}", font, WON, fill)
        key_rows[key] = r
        r += 1

    # 이익률
    r += 1
    _header(ws, r, ["이익률", "당월", "전월", "", "", "전년 동월", "", "누계"])
    r += 1
    sales = key_rows.get("매출액")
    for key, label in (("매출총이익", "매출총이익률"), ("영업이익", "영업이익률"), ("당기순이익", "순이익률")):
        if key not in key_rows or not sales:
            continue
        k = key_rows[key]
        _cell(ws, r, 1, label)
        for col, ci in (("B", 2), ("C", 3), ("F", 6), ("H", 8)):
            _cell(ws, r, ci, f'=IF({col}{sales}=0,"",{col}{k}/{col}{sales})', F, PCT)
        for ci in (4, 5, 7):
            _cell(ws, r, ci, None)
        r += 1

    # 판관비 상위 항목 (당월 금액 기준, 위하고 값으로 정렬)
    items = sorted(expense_items(lines, keys), key=lambda i: -num(lines[i].get("당월")))[:7]
    if items:
        r += 1
        _cell(ws, r, 1, "판매비와관리비 주요 항목 (당월 금액 순)", F_BOLD, border=False)
        r += 1
        _header(ws, r, ["계정과목", "당월", "전월", "전월 대비", "증감률", "판관비 중 비중"])
        total = key_rows.get("판매비와관리비")
        first = r + 1
        for i in items:
            r += 1
            src = rows[i]
            _cell(ws, r, 1, str(lines[i]["계정"]).strip())
            _cell(ws, r, 2, f"=손익계산서!B{src}", F, WON)
            _cell(ws, r, 3, f"=손익계산서!C{src}", F, WON)
            _cell(ws, r, 4, f"=B{r}-C{r}", F, WON)
            _cell(ws, r, 5, f'=IF(C{r}=0,"",(B{r}-C{r})/ABS(C{r}))', F, PCT)
            _cell(ws, r, 6, f'=IF(B{total}=0,"",B{r}/B{total})' if total else "", F, PCT)
        last = r

    # 차트: 당월·전월·전년동월 (매출액·영업이익·당기순이익)
    chart_keys = [k for k in ("매출액", "영업이익", "당기순이익") if k in key_rows]
    if chart_keys:
        base = r + 3
        _cell(ws, base, 1, "차트용", F_NOTE, border=False)
        for j, t in enumerate(["당월", "전월", "전년 동월"], 2):
            _cell(ws, base, j, t, F_NOTE, border=False)
        for n, k in enumerate(chart_keys, 1):
            kr = key_rows[k]
            _cell(ws, base + n, 1, KEY_LABEL.get(k, k), F_NOTE, border=False)
            for j, col in enumerate("BCF", 2):
                _cell(ws, base + n, j, f"={col}{kr}", F_NOTE, WON, border=False)
        chart = BarChart()
        chart.title = "당월 · 전월 · 전년 동월"
        chart.y_axis.numFmt = "#,##0"
        chart.height, chart.width = 7, 16
        data = Reference(ws, min_col=2, max_col=4, min_row=base, max_row=base + len(chart_keys))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=base + 1, max_row=base + len(chart_keys)))
        ws.add_chart(chart, f"A{base + len(chart_keys) + 2}")

    _cell(ws, r + 2, 1, "※ 증감·증감률·이익률은 엑셀 수식으로 계산됩니다. 금액은 위하고 손익계산서 기준입니다.",
          F_NOTE, border=False)
    _widths(ws, [26, 15, 15, 14, 9, 15, 14, 16])
    return key_rows


def write_trend_sheet(ws, client, history):
    months = sorted(history.get(client, {}))[-13:]
    ws.title = "월별추이"
    _cell(ws, 1, 1, f"{client} 월별 추이", F_TITLE, border=False)
    _cell(ws, 2, 1, "보고서를 만들 때마다 한 달씩 쌓입니다 · 단위: 원", F_NOTE, border=False)
    items = [k for k in ("매출액", "매출총이익", "판매비와관리비", "영업이익", "당기순이익")
             if any(k in history[client][m] for m in months)]
    _header(ws, 4, ["연월"] + [KEY_LABEL.get(k, k) for k in items])
    for i, m in enumerate(months, 5):
        _cell(ws, i, 1, m, align="center")
        for j, k in enumerate(items, 2):
            _cell(ws, i, j, history[client][m].get(k, 0), F, WON)
    _widths(ws, [10] + [16] * len(items))
    if len(months) >= 2 and items:
        chart = LineChart()
        chart.title = "월별 매출·이익"
        chart.y_axis.numFmt = "#,##0"
        chart.height, chart.width = 8, 18
        want = [j for j, k in enumerate(items, 2) if k in ("매출액", "영업이익", "당기순이익")]
        for j in want:
            chart.add_data(Reference(ws, min_col=j, min_row=4, max_row=4 + len(months)), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + len(months)))
        ws.add_chart(chart, f"{get_column_letter(len(items) + 3)}4")


def _print_setup(wb):
    for ws in wb.worksheets:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True


def client_report(statement, history, out_dir="."):
    wb = Workbook()
    summary = wb.active
    stmt = wb.create_sheet()
    rows = write_statement_sheet(stmt, statement)
    write_summary_sheet(summary, statement, rows)
    write_trend_sheet(wb.create_sheet(), statement["수임처"], history)
    _print_setup(wb)
    path = Path(out_dir) / f"손익보고_{statement['수임처']}_{statement['연월']}.xlsx"
    wb.save(path)
    return path


# ---- 내부 검토 -----------------------------------------------------------------
def review_flags(statement, settings=None):
    """업체에 보내기 전에 확인할 항목."""
    s = {"sales_change": 0.3, "expense_change": 0.5, "expense_min": 1_000_000, **(settings or {})}
    lines, keys = statement["lines"], find_keys(statement["lines"])
    v = key_values(statement)
    flags = []

    def add(level, item, msg):
        flags.append({"수임처": statement["수임처"], "중요도": level, "항목": item, "내용": msg})

    sales = v.get("매출액", {})
    if not sales or sales.get("당월", 0) == 0:
        add("높음", "매출액", "당월 매출이 0 입니다 (기장 누락 또는 휴업 확인)")
    else:
        for p, label in (("전월", "전월"), ("전년동월", "전년 동월")):
            base = sales.get(p, 0)
            if base and abs(sales["당월"] - base) / abs(base) >= s["sales_change"]:
                add("중간", "매출액", f"{label} 대비 {((sales['당월'] - base) / abs(base)):+.0%} 변동")
    op = v.get("영업이익", {})
    if op and op.get("당월", 0) < 0 <= op.get("전월", 0):
        add("높음", "영업이익", "당월 적자 전환")
    net = v.get("당기순이익", {})
    if net and net.get("누계", 0) < 0:
        add("중간", "당기순이익", "누계 적자")
    for i in expense_items(lines, keys):
        cur, prev = num(lines[i].get("당월")), num(lines[i].get("전월"))
        name = str(lines[i]["계정"]).strip()
        if max(cur, prev) < s["expense_min"]:
            continue
        if prev == 0 and cur > 0:
            add("중간", name, f"전월 없던 비용 {cur:,.0f}원 발생")
        elif prev and abs(cur - prev) / abs(prev) >= s["expense_change"]:
            add("낮음", name, f"전월 대비 {((cur - prev) / abs(prev)):+.0%} ({prev:,.0f} → {cur:,.0f})")
    if "매출액" in keys and "매출총이익" in keys and "매출원가" not in keys and entity_type(lines) == "법인":
        add("낮음", "매출원가", "매출원가 줄이 없습니다 (업종 확인)")
    return flags


def internal_report(statements, ym, out_dir=".", settings=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "수임처요약"
    _cell(ws, 1, 1, f"월별 손익 내부 검토 ({ym})", F_TITLE, border=False)
    _cell(ws, 2, 1, f"{datetime.now():%Y-%m-%d %H:%M} 작성 · 내부용 (업체에 보내지 않음) · 단위: 원", F_NOTE,
          border=False)
    heads = ["수임처", "구분", "매출액", "전월 매출", "전월 대비", "전년 동월 매출", "전년 대비",
             "영업이익", "영업이익률", "당기순이익", "누계 매출", "누계 순이익", "검토 항목 수"]
    _header(ws, 4, heads)
    all_flags = []
    for i, st in enumerate(statements, 5):
        v = key_values(st)
        g = lambda k, p: v.get(k, {}).get(p, 0)
        flags = review_flags(st, settings)
        all_flags += flags
        fill = FILL_FLAG if any(f["중요도"] == "높음" for f in flags) else None
        vals = [st["수임처"], entity_type(st["lines"]), g("매출액", "당월"), g("매출액", "전월"), None,
                g("매출액", "전년동월"), None, g("영업이익", "당월"), None, g("당기순이익", "당월"),
                g("매출액", "누계"), g("당기순이익", "누계"), len(flags)]
        for j, val in enumerate(vals, 1):
            _cell(ws, i, j, val, F, WON if j in (3, 4, 6, 8, 10, 11, 12) else None, fill)
        _cell(ws, i, 5, f'=IF(D{i}=0,"",(C{i}-D{i})/ABS(D{i}))', F, PCT, fill)
        _cell(ws, i, 7, f'=IF(F{i}=0,"",(C{i}-F{i})/ABS(F{i}))', F, PCT, fill)
        _cell(ws, i, 9, f'=IF(C{i}=0,"",H{i}/C{i})', F, PCT, fill)
    _widths(ws, [20, 7, 15, 15, 10, 15, 10, 15, 10, 15, 16, 16, 10])
    ws.freeze_panes = "B5"

    fs = wb.create_sheet("검토항목")
    _cell(fs, 1, 1, f"검토 항목 ({ym})", F_TITLE, border=False)
    _cell(fs, 2, 1, "확인 결과는 '확인' 칸에 적어 주세요 (예: 정상, 전표 누락 → 수정)", F_NOTE, border=False)
    _header(fs, 4, ["수임처", "중요도", "항목", "내용", "확인"])
    order = {"높음": 0, "중간": 1, "낮음": 2}
    for i, f in enumerate(sorted(all_flags, key=lambda f: (order[f["중요도"]], f["수임처"])), 5):
        fill = FILL_FLAG if f["중요도"] == "높음" else None
        for j, k in enumerate(["수임처", "중요도", "항목", "내용"], 1):
            _cell(fs, i, j, f[k], F, fill=fill)
        _cell(fs, i, 5, None, F, fill=PatternFill("solid", fgColor="FFFFCC"))
    if not all_flags:
        _cell(fs, 5, 1, "자동 검토 항목이 없습니다.", F_NOTE, border=False)
    _widths(fs, [20, 8, 22, 50, 30])
    fs["E4"].comment = Comment("세무사님 확인 메모 칸 (노란색)", "자동화")

    _print_setup(wb)
    path = Path(out_dir) / f"손익검토_{ym}.xlsx"
    wb.save(path)
    return path, all_flags


def build_reports(statements, out_dir=".", history_path=HISTORY_PATH, settings=None):
    """업체별 보고서 + 내부 검토 파일을 만들고 월별 기록을 갱신한다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    history = load_history(history_path)
    for st in statements:
        remember(history, st)
    save_history(history, history_path)
    paths = [client_report(st, history, out_dir) for st in statements]
    ym = statements[0]["연월"] if statements else datetime.now().strftime("%Y-%m")
    internal, flags = internal_report(statements, ym, out_dir, settings)
    return paths, internal, flags

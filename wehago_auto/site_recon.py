"""처음 보는 사이트(예: 위멤버스) 구조 조사.

세무사님이 직접 로그인하고 평소처럼 화면을 열고 [조회]·[엑셀 다운로드] 를 하면,
그동안 사이트가 주고받은 데이터의 '구조'만 기록한다.
- 기록함: 주소(경로), 데이터 항목 이름과 자료형, 목록 건수, 누른 버튼·메뉴 이름, 내려받은 엑셀의 첫 줄(항목 이름)
- 기록 안 함: 금액, 상호, 사업자번호 등 실제 값 (글자는 길이만, 숫자는 자료형만)
"""

import csv
import io
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from wehago import start, stop

# 누른 버튼·메뉴 이름 기록 (숫자는 # 로 가림). 페이지가 바뀌어도 이어서 기록되도록 Python 으로 바로 보낸다.
LOG_JS = r"""
(() => {
  const send = o => { try { window.__reconLog && window.__reconLog(o); } catch (e) {} };
  const text = el => {
    const t = (el && (el.innerText || el.value || el.title || el.getAttribute('aria-label') || '') || '')
      .trim().replace(/\d/g, '#').replace(/\s+/g, ' ');
    return t.length <= 30 ? t : t.slice(0, 30) + '…';
  };
  document.addEventListener('click', e => {
    const el = e.target.closest('button, a, li, [role=button], [role=menuitem], [role=tab], label, span') || e.target;
    send({type: 'click', tag: el.tagName.toLowerCase(), text: text(el), page: location.pathname});
  }, true);
  window.addEventListener('load', () => send({type: 'page', page: location.pathname, title: document.title}));
})();
"""


def masked(value, depth=0):
    """구조만 남긴다: dict → 키별, list → 건수 + 첫 항목 구조, 글자 → str(길이), 숫자 → 자료형."""
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        return {k: masked(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return [f"len={len(value)}"] + ([masked(value[0], depth + 1)] if value else [])
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}[-./]?\d{2}[-./]?\d{2}", value):
            return "date"
        return f"str({len(value)})"
    return type(value).__name__


def form_keys(request):
    data = request.post_data or ""
    try:
        return {"json": masked(json.loads(data))}
    except Exception:
        return {"form_keys": re.findall(r"(?:^|&)([^=&]+)=", data)[:80]} if data else {}


def _header_only(rows):
    """항목 이름 줄(글자만 2칸 이상인 첫 줄)만 글자를 남기고, 나머지 줄은 자료형만 남긴다."""
    def is_header(row):
        cells = [c for c in row if c not in (None, "")]
        return len(cells) >= 2 and all(isinstance(c, str) and not re.search(r"\d{3,}", c) for c in cells)

    head = next((i for i, r in enumerate(rows) if is_header(r)), None)
    out = []
    for i, row in enumerate(rows):
        if i == head:
            out.append(["(항목 이름)"] + [c if c is not None else "" for c in row])
        else:
            out.append(["(값)"] + [type(c).__name__ if c not in (None, "") else "" for c in row])
    return out


def file_headers(path):
    """내려받은 엑셀/CSV 의 앞부분에서 항목 이름 줄만 (실제 값은 자료형만)."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:3]:
            rows = [list(r[:40]) for r in ws.iter_rows(max_row=8, values_only=True)]
            out += [[f"[{len(out)}] 시트"]] + _header_only(rows)
        return out
    if path.suffix.lower() in (".csv", ".txt"):
        raw = path.read_bytes()[:20000]
        text = ""
        for enc in ("utf-8-sig", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        rows = [[c if not re.fullmatch(r"[\d,.\-]+", c) else 0 for c in r[:40]]
                for r in list(csv.reader(io.StringIO(text)))[:8]]
        return _header_only(rows)
    return [[f"(형식 {path.suffix}, 내용 미확인)"]]


def site_recon_session(name, url="", out_dir="."):
    out_dir = Path(out_dir)
    events, responses, downloads = [], [], []
    with sync_playwright() as p:
        context = start(p)
        context.expose_binding("__reconLog", lambda source, o: events.append(o))
        context.add_init_script(LOG_JS)
        context.on("response", lambda r: responses.append(r)
                   if r.request.resource_type in ("xhr", "fetch") else None)
        tmp = Path(tempfile.mkdtemp())

        def on_download(d):
            try:
                path = tmp / d.suggested_filename
                d.save_as(path)
                downloads.append({"file_ext": path.suffix, "name_pattern": re.sub(r"\d", "#", path.stem),
                                  "header_rows": file_headers(path)})
                path.unlink(missing_ok=True)
            except Exception as e:
                downloads.append({"error": str(e)})

        page = context.pages[0] if context.pages else context.new_page()
        context.on("page", lambda pg: pg.on("download", on_download))
        page.on("download", on_download)
        if url:
            page.goto(url)
        print(f"\n[{name} 조사] 열린 창에서 직접 해 주세요:")
        if not url:
            print(f"  0) 주소창에 {name} 주소를 입력해 들어갑니다")
        print("  1) 로그인 (세무사 계정)")
        print("  2) 수임처(사업장) 하나를 고릅니다")
        print("  3) 매출 화면들(세금계산서·카드·배달앱)과 매입 화면들을 차례로 열고 지난달로 [조회]")
        print("  4) 엑셀 다운로드 버튼이 있으면 한 번씩 눌러 주세요 (파일 내용은 저장하지 않고 항목 이름만 봅니다)")
        input("다 하셨으면 Enter를 누르세요...")
        how = input("어떤 순서로 하셨는지 한 줄로 적어 주세요 (예: 수임처 선택 → 매출관리 → 카드매출 → 조회): ")

        hosts = sorted({urlsplit(r.url).netloc for r in responses})
        items = []
        for r in responses:
            path = urlsplit(r.url).path
            if re.search(r"collect|analytics|log|beacon|sentry|lpevent", path, re.I):
                continue
            item = {"host": urlsplit(r.url).netloc, "method": r.request.method, "path": re.sub(r"\d{5,}", "#", path),
                    "status": r.status}
            if r.request.method != "GET":
                item["request"] = form_keys(r.request)
            if "json" in r.headers.get("content-type", ""):
                try:
                    item["response"] = masked(r.json())
                except Exception:
                    pass
            items.append(item)
        result = {"site": name, "start_url": url, "how_by_user": how, "hosts": hosts,
                  "actions": events[-200:], "downloads": downloads, "responses": items[-200:],
                  "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        out = out_dir / f"{name}조사_결과.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        stop(context)
    print(f"\n조사 결과를 저장했습니다: {out}  — 이 파일을 Claude에게 보내 주세요.")
    print("(항목 이름·버튼 이름·데이터 구조만 들어 있고, 금액·상호·사업자번호 값은 들어 있지 않습니다)")

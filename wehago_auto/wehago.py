"""위하고 화면 조작 (Playwright).

원칙
- 로그인은 사용자가 직접 한다. 아이디/비밀번호/인증서는 다루지 않는다.
- 자동 실행이 실패한 단계는 사용자에게 직접 해 달라고 요청하고 이어서 진행한다.
- '전송', '삭제' 같은 단어가 있는 버튼은 절대 누르지 않는다.
"""

import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

WEHAGO_URL = "https://www.wehago.com/"
FORBIDDEN_WORDS = ("전송", "삭제", "마감", "취소")


def launch(p):
    """PC에 이미 설치된 Edge → Chrome 순으로 띄운다 (브라우저 추가 설치 불필요)."""
    for channel in ("msedge", "chrome", None):
        try:
            browser = p.chromium.launch(channel=channel, headless=False)
            return browser
        except Exception:
            continue
    raise RuntimeError("Edge 또는 Chrome 브라우저를 찾지 못했습니다.")


class Wehago:
    def __init__(self, context):
        self.context = context
        self.page = context.new_page()
        self.log = []  # 단계별 성공/실패 기록

    # ---- 기본 도구 -------------------------------------------------------
    def find(self, make_locator, timeout=6000):
        """모든 프레임에서 화면에 보이는 첫 요소를 찾는다."""
        deadline = time.time() + timeout / 1000
        while time.time() < deadline:
            for frame in self.page.frames:
                loc = make_locator(frame)
                try:
                    for i in range(min(loc.count(), 10)):
                        if loc.nth(i).is_visible():
                            return loc.nth(i)
                except Exception:
                    pass
            time.sleep(0.3)
        raise LookupError("화면에서 요소를 찾지 못함")

    def click(self, loc):
        text = (loc.inner_text(timeout=2000) or "").strip()
        if any(w in text for w in FORBIDDEN_WORDS):
            raise PermissionError(f"안전 규칙상 누르지 않는 버튼: {text}")
        before = len(self.context.pages)
        loc.click()
        self.page.wait_for_timeout(1000)
        # 새 창/탭이 열렸으면 그 창으로 이동
        for _ in range(10):
            if len(self.context.pages) > before:
                self.page = self.context.pages[-1]
                self.page.wait_for_load_state()
                break
            self.page.wait_for_timeout(300)

    def step(self, title, action):
        print(f"\n[{title}]")
        try:
            action()
            print("  → 자동 완료")
            self.log.append({"단계": title, "결과": "자동 완료"})
        except Exception as e:
            print(f"  → 자동 실행 실패 ({e})")
            input(f"  위하고 화면에서 직접 '{title}' 을(를) 해 주시고 Enter를 누르세요...")
            self.page = self.context.pages[-1]
            self.log.append({"단계": title, "결과": f"수동 처리 ({type(e).__name__}: {e})"})

    def _filter(self, label):
        """조회 조건 칸(<strong class=inquiry_tit>이름</strong> + 옆 div)을 찾는다."""
        exact = re.compile(rf"^\s*{re.escape(label)}\s*$")
        lab = self.find(lambda f: f.locator("strong.inquiry_tit").filter(has_text=exact))
        return lab.locator("xpath=following-sibling::div[1]")

    def filter_value(self, label):
        box = self._filter(label)
        fake = box.locator("span.fakeinput")
        if fake.count():
            return fake.first.inner_text().strip()
        inp = box.locator("input")
        return inp.first.input_value().strip() if inp.count() else ""

    def choose(self, label, option):
        """'구분' 같은 조회 조건 드롭다운에서 항목을 고른다."""
        if self.filter_value(label) == option:
            return  # 이미 선택되어 있음
        box = self._filter(label)
        opener = box.locator("span.fakeinput, button").first
        self.click(opener)
        self.click(self.find(lambda f: f.get_by_text(option, exact=True)))
        if self.filter_value(label) != option:
            raise RuntimeError(f"'{label}' 이(가) '{option}' 으로 바뀌지 않음")

    # ---- 사용자가 정한 작업 순서 -------------------------------------------
    def wait_login(self):
        self.page.goto(WEHAGO_URL)
        input("\n위하고에 직접 로그인하신 뒤, 수임처 목록 화면이 보이면 Enter를 누르세요...")
        self.page = self.context.pages[-1]

    def open_card_purchase_list(self, client):
        def open_client_accounting():
            box = self.find(lambda f: f.get_by_role("textbox"))
            box.fill(client)
            box.press("Enter")
            self.page.wait_for_timeout(1500)
            name = self.find(lambda f: f.get_by_text(client))
            row_button = name.locator(
                "xpath=ancestor::*[.//*[normalize-space(text())='회계']][1]"
                "//*[normalize-space(text())='회계']"
            ).first
            self.click(row_button)

        def open_credit_card():
            self.click(self.find(lambda f: f.get_by_text("신용카드", exact=True)))

        def check_all_cards():
            value = self.filter_value("카드")
            # 아무 카드도 고르지 않으면 검색 안내문이 보이는데, 이것도 전체 카드다.
            if value != "전체거래처" and "검색" not in value:
                raise RuntimeError(f"카드 칸이 '{value}' 임")

        def search():
            self.click(self.find(lambda f: f.get_by_role("button", name="조회")))

        self.step(f"수임처 '{client}' 의 [회계] 열기", open_client_accounting)
        self.step("자동전표처리 [신용카드] 열기", open_credit_card)
        self.step("구분을 '2. 매입' 으로 변경", lambda: self.choose("구분", "2. 매입"))
        self.step("카드를 '전체거래처' 로 확인", check_all_cards)
        self.step("전표상태를 '전체' 로 변경", lambda: self.choose("전표상태", "전체"))
        self.step("[조회] 누르기", search)
        # 거래처별 정렬은 화면에서 하지 않고, 읽어 온 데이터를 프로그램이 거래처별로 묶는다.


# ---- 화면 구조 조사 (recon) ------------------------------------------------
# 표 내용(가맹점명·금액)은 모두 '·' 로 가리고, 아래 단어만 남긴다.
KEEP_WORDS = [
    "일자", "Code", "거래처", "구분", "품명", "공급가액", "세액", "비과세", "합계",
    "국세청", "업태", "종목", "유형", "차변계정", "대변계정", "관리", "전표상태",
    "확정가능", "미추천", "조회", "기간", "자료", "카드", "전체", "전체거래처",
    "2. 매입", "1. 매출", "1. 국세청", "일반", "카과", "카면", "법인", "간이", "면세",
    "업태,종목 조회", "전표전송", "전표처리",
]

_MASKED_DOM_JS = """
(keep) => {
  const KEEP = new Set(keep);
  const SAFE_ATTR = new Set(['class', 'id', 'role', 'type', 'name', 'tabindex', 'style',
                             'aria-rowindex', 'aria-colindex', 'contenteditable']);
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll('script,style,svg,noscript').forEach(e => e.remove());
  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const t of texts) {
    const v = t.nodeValue.trim();
    if (v && !KEEP.has(v)) t.nodeValue = '·';
  }
  for (const el of clone.querySelectorAll('*')) {
    for (const a of [...el.attributes]) {
      if (SAFE_ATTR.has(a.name)) continue;
      if (a.name.startsWith('data-') && KEEP.has(a.value)) continue;
      el.setAttribute(a.name, KEEP.has(a.value) ? a.value : '·');
    }
  }
  return clone.outerHTML.replace(/>\\s+</g, '><');
}
"""

_PROBE_JS = """
(words) => {
  const chain = el => {
    const out = [];
    for (let n = el; n && out.length < 10; n = n.parentElement)
      out.push(n.tagName.toLowerCase() + (n.className && typeof n.className === 'string'
        ? '.' + n.className.trim().split(/\\s+/).join('.') : ''));
    return out;
  };
  const headers = {};
  for (const w of words) {
    headers[w] = [...document.querySelectorAll('body *')]
      .filter(e => e.childElementCount === 0 && e.textContent.trim() === w)
      .slice(0, 3).map(chain);
  }
  return {
    url_path: location.pathname,
    globals: Object.keys(window).filter(k => /grid|obt|real|wijmo|tui|dews|sheet/i.test(k)).slice(0, 50),
    canvases: [...document.querySelectorAll('canvas')].map(c => [c.width, c.height]),
    tables: document.querySelectorAll('table').length,
    role_grid: document.querySelectorAll('[role=grid]').length,
    headers,
  };
}
"""


def shape(value, depth=0):
    """JSON 응답의 구조(키 이름과 자료형)만 남기고 값은 버린다."""
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in list(value.items())[:80]}
    if isinstance(value, list):
        return [f"len={len(value)}"] + ([shape(value[0], depth + 1)] if value else [])
    return type(value).__name__


def recon(client, out_path):
    import json

    with sync_playwright() as p:
        browser = launch(p)
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        responses = []
        context.on("response", lambda r: responses.append(r)
                   if r.request.resource_type in ("xhr", "fetch") else None)

        w = Wehago(context)
        w.wait_login()
        responses.clear()
        w.open_card_purchase_list(client)
        input("\n카드 매입 내역 표가 화면에 보이면 Enter를 누르세요 (화면 구조를 조사합니다)...")

        frames = []
        for frame in w.page.frames:
            try:
                frames.append({
                    "frame_url_path": urlsplit(frame.url).path,
                    "probe": frame.evaluate(_PROBE_JS, KEEP_WORDS[:17]),
                    "masked_html": frame.evaluate(_MASKED_DOM_JS, KEEP_WORDS)[:300_000],
                })
            except Exception as e:
                frames.append({"frame_url_path": urlsplit(frame.url).path, "error": str(e)})

        network = []
        for r in responses[-80:]:
            item = {"method": r.request.method, "path": urlsplit(r.url).path,
                    "status": r.status, "type": r.headers.get("content-type", "")}
            if "json" in item["type"]:
                try:
                    item["shape"] = shape(r.json())
                except Exception:
                    pass
            network.append(item)

        result = {"steps": w.log, "frames": frames, "network": network}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        browser.close()
    print(f"\n조사 결과를 저장했습니다: {out_path}")
    print("가맹점명·금액 등 표 내용은 '·' 로 가려져 있습니다. 이 파일을 Claude에게 보내 주세요.")


# ---- 2차 조사: 표(RealGrid) 구조와 저장 방식 --------------------------------
CARD_LIST_PATH = "/smarta/saac0105/6/"  # 카드 매입 목록을 내려주는 위하고 API

# 화면의 표는 RealGrid(캔버스)로 그려져서 글자를 읽을 수 없다.
# 대신 표 객체를 찾아서 칸 정의(칸 이름, 코드→표시값 목록)만 꺼낸다.
_GRID_JS = r"""
() => {
  const isGrid = o => o && typeof o === 'object'
    && typeof o.getColumns === 'function'
    && (typeof o.getDataSource === 'function' || typeof o.getDataProvider === 'function');
  const found = [], seen = new Set();
  for (const g of (window.__wehagoGrids || [])) found.push([g, 'hook']);
  const visit = (root, path) => {
    const queue = [[root, path, 0]];
    let budget = 30000;
    while (queue.length && budget-- > 0) {
      const [o, p, d] = queue.shift();
      if (!o || typeof o !== 'object' || seen.has(o)) continue;
      seen.add(o);
      if (isGrid(o)) { found.push([o, p]); continue; }
      if (d >= 4 || o instanceof Node || o === window) continue;
      let keys = [];
      try { keys = Object.keys(o).slice(0, 200); } catch (e) {}
      for (const k of keys) {
        let v; try { v = o[k]; } catch (e) { continue; }
        if (v && typeof v === 'object') queue.push([v, p + '.' + k, d + 1]);
      }
    }
  };
  for (const k of ['Grids', 'RealGrid', 'RealGridJS']) {
    try { if (window[k]) visit(window[k], 'window.' + k); } catch (e) {}
  }
  // React 컴포넌트에 붙어 있는 표 객체 찾기
  for (const el of document.querySelectorAll('.realgrid_z, .sao_grid_content, canvas')) {
    for (let n = el, i = 0; n && i < 8; n = n.parentElement, i++) {
      const key = Object.keys(n).find(k => k.startsWith('__reactInternalInstance') || k.startsWith('__reactFiber'));
      if (!key) continue;
      for (let f = n[key], j = 0; f && j < 40; f = f.return, j++) {
        for (const part of ['stateNode', 'memoizedProps', 'memoizedState']) {
          try { if (f[part] && typeof f[part] === 'object' && !(f[part] instanceof Node)) visit(f[part], 'react.' + part); } catch (e) {}
        }
        if (f._currentElement || f._instance) { try { visit(f._instance, 'react15._instance'); } catch (e) {} }
      }
      if (key.startsWith('__reactInternalInstance')) {
        // React 15: DOM 노드 → 그 노드를 그린 컴포넌트(_owner)를 따라 올라간다
        let inst = n[key]._currentElement && n[key]._currentElement._owner;
        for (let j = 0; inst && j < 15; j++) {
          try { visit(inst._instance, 'react15.owner'); } catch (e) {}
          inst = inst._currentElement && inst._currentElement._owner;
        }
      }
      if (n._reactInternalInstance) {
        for (let f = n._reactInternalInstance, j = 0; f && j < 40; f = f._hostParent || f._currentElement?._owner, j++) {
          try { visit(f._instance || f, 'react15'); } catch (e) {}
        }
      }
    }
  }
  const pick = (c) => {
    const out = {};
    for (const k of ['name', 'fieldName', 'type', 'values', 'labels', 'lookupDisplay', 'lookupSourceId',
                     'visible', 'editable', 'readOnly', 'width', 'displayIndex'])
      if (c[k] !== undefined) out[k] = c[k];
    const h = c.header; out.header = typeof h === 'string' ? h : (h && h.text);
    const e = c.editor; if (e) out.editor = typeof e === 'string' ? e : (e.type || e.constructor?.name || Object.keys(e));
    if (c.columns) out.columns = c.columns.map(pick);
    return out;
  };
  const uniq = [...new Map(found.map(x => [x[0], x])).values()];
  return uniq.map(([g, path]) => {
    const r = {path};
    try { r.columns = (g.getColumns() || []).map(pick); } catch (e) { r.columns_error = String(e); }
    try {
      const ds = g.getDataSource ? g.getDataSource() : g.getDataProvider();
      r.rowCount = ds.getRowCount();
      r.fields = (ds.getFields ? ds.getFields() : []).map(f => f.fieldName || f.orgFieldName || f);
    } catch (e) { r.ds_error = String(e); }
    try { r.itemCount = g.getItemCount(); } catch (e) {}
    const proto = Object.getPrototypeOf(g);
    r.methods = proto ? Object.getOwnPropertyNames(proto).filter(n => /^(set|get|commit|cancel|show|orderBy|beginUpdate|endUpdate|click|onCell|onEdit|checkItem|getCell|setCurrent|getCurrent)/.test(n)).slice(0, 200) : [];
    r.handlers = Object.keys(g).filter(k => /^on[A-Z]/.test(k) && typeof g[k] === 'function');
    return r;
  });
}
"""

# 위하고 페이지가 RealGrid 표를 만들 때 그 표 객체를 기억해 두는 스크립트.
# 표의 공개 메서드를 감싸서 (1) 표 객체를 window.__wehagoGrids 에 모으고
# (2) 추적 중일 때 어떤 메서드가 불렸는지 센다. 위하고 동작은 바꾸지 않는다.
GRID_HOOK_JS = r"""
(() => {
  if (window.__wehagoHooked) return;
  window.__wehagoHooked = true;
  window.__wehagoGrids = [];
  window.__wehagoTrace = null;
  const done = new WeakSet();
  const wrap = (cls, kind) => {
    for (let proto = cls && cls.prototype; proto && proto !== Object.prototype;
         proto = Object.getPrototypeOf(proto)) {
      if (done.has(proto)) continue;
      done.add(proto);
      for (const name of Object.getOwnPropertyNames(proto)) {
        if (name === 'constructor' || !/^[a-z][A-Za-z]{3,}$/.test(name)) continue;
        const d = Object.getOwnPropertyDescriptor(proto, name);
        if (!d || typeof d.value !== 'function' || !d.writable) continue;
        const orig = d.value;
        proto[name] = function (...args) {
          if (kind === 'grid' && !window.__wehagoGrids.includes(this)) window.__wehagoGrids.push(this);
          const t = window.__wehagoTrace;
          if (t) { const k = kind + '.' + name; t[k] = (t[k] || 0) + 1; }
          return orig.apply(this, args);
        };
      }
    }
  };
  setInterval(() => {
    for (const ns of [window.RealGrid, window.RealGridJS]) {
      if (!ns) continue;
      try {
        wrap(ns.GridView, 'grid'); wrap(ns.TreeView, 'grid');
        wrap(ns.LocalDataProvider, 'data'); wrap(ns.LocalTreeDataProvider, 'data');
      } catch (e) {}
    }
  }, 300);
})();
"""

# 표 데이터 중 코드값 칸만 꺼낸다 (수정 전후 비교용, 가맹점명·금액 제외)
SNAPSHOT_FIELDS = ["ty_mth", "ty_mth2", "ty_jungstat", "ty_gongjea", "cd_acctit_cha", "nm_acctit_cha"]

_SNAPSHOT_JS = r"""
(fields) => (window.__wehagoGrids || []).map(g => {
  try {
    const ds = g.getDataSource ? g.getDataSource() : g.getDataProvider();
    const rows = ds.getJsonRows ? ds.getJsonRows(0, -1) : [];
    return rows.map(r => fields.map(f => r[f] === undefined ? null : r[f]));
  } catch (e) { return String(e); }
})
"""


def diff_snapshots(before, after):
    out = []
    for gi, (b, a) in enumerate(zip(before, after)):
        if not isinstance(b, list) or not isinstance(a, list):
            continue
        for ri, (rb, ra) in enumerate(zip(b, a)):
            for fi, (vb, va) in enumerate(zip(rb, ra)):
                if vb != va:
                    out.append({"grid": gi, "row": ri, "field": SNAPSHOT_FIELDS[fi],
                                "before": vb, "after": va})
        if len(a) != len(b):
            out.append({"grid": gi, "row_count": [len(b), len(a)]})
    return out[:200]


# 목록 데이터 중 코드값만 세어 본다 (가맹점명·금액은 담지 않음)
COUNT_FIELDS = ["ty_jungstat", "ty_trade", "ty_gongjea", "ty_mth", "ty_mth2", "ty_biz",
                "provider", "freetax", "gj_gubun", "nm_acctit_cha", "nm_acctit_dae",
                "cd_acctit_cha", "cnt_recommend_cha", "elec_confirm", "jasan"]


def value_counts(rows):
    out = {}
    for key in COUNT_FIELDS:
        counts = {}
        for r in rows:
            v = str(r.get(key))
            counts[v] = counts.get(v, 0) + 1
        out[key] = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:40])
    return out


def body_shape(request):
    data = request.post_data or ""
    try:
        import json
        return shape(json.loads(data))
    except Exception:
        keys = re.findall(r"(?:^|&)([^=&]+)=", data)
        return {"form_keys": keys[:80]} if keys else {"length": len(data)}


def recon2(client, out_path):
    import json

    with sync_playwright() as p:
        browser = launch(p)
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        lists = []
        context.on("response", lambda r: lists.append(r)
                   if urlsplit(r.url).path == CARD_LIST_PATH and r.request.method == "POST" else None)

        w = Wehago(context)
        w.wait_login()
        w.open_card_purchase_list(client)
        input("\n카드 매입 내역 표가 화면에 보이면 Enter를 누르세요...")

        grids = []
        for frame in w.page.frames:
            try:
                grids += frame.evaluate(_GRID_JS)
            except Exception as e:
                grids.append({"frame_error": str(e)})
        counts = {}
        if lists:
            try:
                counts = value_counts(lists[-1].json().get("data", []))
            except Exception as e:
                counts = {"error": str(e)}

        # 사용자가 한 건을 직접 고칠 때 위하고가 어떤 요청을 보내는지 기록
        writes = []
        context.on("request", lambda r: writes.append(r)
                   if r.method in ("POST", "PUT", "PATCH", "DELETE")
                   and r.resource_type in ("xhr", "fetch") else None)
        print("\n표에서 아무 거래 한 건의 [유형] 을 다른 값으로 바꾸고, 다시 원래 값으로 되돌려 주세요.")
        print("그다음 같은 건의 [차변계정] 도 바꿨다가 원래대로 되돌려 주세요.")
        input("다 하셨으면 Enter를 누르세요 (전표전송은 누르지 마세요)...")
        edits = [{"method": r.method, "path": urlsplit(r.url).path, "body": body_shape(r)}
                 for r in writes if "/collect" not in r.url and "lpevent" not in r.url]

        result = {"steps": w.log, "grids": grids, "code_counts": counts, "edit_requests": edits}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        browser.close()
    print(f"\n조사 결과를 저장했습니다: {out_path}")
    print("가맹점명·금액 등 표 내용은 들어 있지 않습니다. 이 파일을 Claude에게 보내 주세요.")


# ---- 미리보기 + 3차 조사 ----------------------------------------------------
def preview_session(client, out_dir="."):
    """위하고에서 카드 목록을 읽어 분류 미리보기를 만든다 (위하고에는 쓰지 않음).

    이어서 사용자가 한 건을 고쳤다 되돌릴 때 표 안에서 무슨 일이 일어나는지 기록한다.
    """
    import json
    import webbrowser
    from datetime import datetime
    from pathlib import Path

    import codes as codes_mod
    from classifier import load_rules, load_settings
    from preview import build_groups, render

    out_dir = Path(out_dir)
    with sync_playwright() as p:
        browser = launch(p)
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        context.add_init_script(GRID_HOOK_JS)
        lists = []
        context.on("response", lambda r: lists.append(r)
                   if urlsplit(r.url).path == CARD_LIST_PATH and r.request.method == "POST" else None)

        w = Wehago(context)
        w.wait_login()
        w.open_card_purchase_list(client)
        input("\n카드 매입 내역 표가 화면에 보이면 Enter를 누르세요...")

        def each_frame(js, arg=None):
            out = []
            for frame in w.page.frames:
                try:
                    out.append(frame.evaluate(js, arg) if arg is not None else frame.evaluate(js))
                except Exception as e:
                    out.append({"frame_error": str(e)})
            return out

        grids = [g for res in each_frame(_GRID_JS) if isinstance(res, list) for g in res]
        data = []
        if lists:
            try:
                data = lists[-1].json().get("data", [])
            except Exception as e:
                print(f"목록 데이터를 읽지 못했습니다: {e}")
        if not data:
            print("카드 목록 데이터를 찾지 못했습니다. [조회] 를 한 번 더 누른 뒤 Enter를 누르세요.")
            input()
            if lists:
                data = lists[-1].json().get("data", [])

        codes, confirmed = codes_mod.merge_grid_labels(grids)
        note = ("코드 표시값: " + ", ".join(
            f"{f}={'확인됨' if f in confirmed else '추정'}" for f in codes_mod.TENTATIVE))
        rows = [codes_mod.to_row(d, codes) for d in data]
        groups = build_groups(rows, client, load_rules(), load_settings())
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        report = out_dir / f"미리보기_{client}_{stamp}.html"
        report.write_text(render(client, rows, groups, note), encoding="utf-8")
        webbrowser.open(report.resolve().as_uri())
        print(f"\n미리보기를 열었습니다: {report}  ({len(rows)}건, 거래처 {len(groups)}곳)")

        # 3차 조사: 한 건 수정 → 원복 동안 표 내부 변화 기록
        before = [s for res in each_frame(_SNAPSHOT_JS, SNAPSHOT_FIELDS) for s in res]
        each_frame("() => { window.__wehagoTrace = {}; }")
        sent = []
        context.on("request", lambda r: sent.append(r)
                   if r.resource_type in ("xhr", "fetch") else None)
        print("\n[조사] 위하고 표에서 아무 거래 한 건의")
        print("  1) [유형] 을 다른 값으로 바꾸고 → 전표상태가 어떻게 되는지 보신 뒤")
        print("  2) [차변계정] 도 다른 계정으로 바꿔 주세요.")
        input("바꾸셨으면 Enter를 누르세요 (아직 되돌리지 마세요)...")
        changed = [s for res in each_frame(_SNAPSHOT_JS, SNAPSHOT_FIELDS) for s in res]
        trace = each_frame("() => window.__wehagoTrace")
        requests = [{"method": r.method, "path": urlsplit(r.url).path,
                     "body": body_shape(r) if r.method != "GET" else None}
                    for r in sent if "/collect" not in r.url and "lpevent" not in r.url]
        input("\n이제 그 건을 원래 값으로 되돌리시고 Enter를 누르세요 (전표전송은 누르지 마세요)...")

        result = {
            "steps": w.log,
            "grids": grids,
            "codes_used": codes,
            "codes_confirmed": sorted(confirmed),
            "row_count": len(rows),
            "edit_diff": diff_snapshots(before, changed),
            "edit_trace": [t for t in trace if t],
            "edit_requests": requests,
        }
        out = out_dir / "recon3_결과.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        browser.close()
    print(f"\n조사 결과를 저장했습니다: {out}")
    print("미리보기 HTML 은 PC 에만 두시고, recon3_결과.json 만 Claude에게 보내 주세요.")

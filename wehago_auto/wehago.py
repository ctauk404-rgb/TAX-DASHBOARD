"""위하고 화면 조작 (Playwright).

원칙
- 로그인은 사용자가 직접 한다. 아이디/비밀번호/인증서는 다루지 않는다.
- 자동 실행이 실패한 단계는 사용자에게 직접 해 달라고 요청하고 이어서 진행한다.
- '전송', '삭제' 같은 단어가 있는 버튼은 절대 누르지 않는다.
"""

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

    def choose(self, label, option):
        """'구분' 같은 이름표 옆 드롭다운에서 항목을 고른다."""
        lab = self.find(lambda f: f.get_by_text(label, exact=True))
        native = lab.locator("xpath=following::select[1]")
        if native.count():
            native.select_option(label=option)
            return
        box = lab.locator(
            "xpath=following::*[@role='combobox' or @role='listbox'"
            " or contains(translate(@class,'SELECTCOMBODROP','selectcombodrop'),'select')"
            " or contains(translate(@class,'SELECTCOMBODROP','selectcombodrop'),'combo')"
            " or contains(translate(@class,'SELECTCOMBODROP','selectcombodrop'),'drop')][1]"
        )
        if option in (box.inner_text(timeout=2000) or ""):
            return  # 이미 선택되어 있음
        self.click(box)
        self.click(self.find(lambda f: f.get_by_text(option, exact=True)))
        if option not in (box.inner_text(timeout=2000) or ""):
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
            field = self.find(lambda f: f.get_by_text("카드", exact=True))
            near = field.locator("xpath=following::input[1]")
            value = near.input_value(timeout=2000) if near.count() else ""
            if "전체" not in value:
                raise RuntimeError(f"카드 칸이 '{value}' 임")

        def search():
            self.click(self.find(lambda f: f.get_by_role("button", name="조회")))

        def sort_by_merchant():
            self.click(self.find(lambda f: f.get_by_text("거래처", exact=True)))

        self.step(f"수임처 '{client}' 의 [회계] 열기", open_client_accounting)
        self.step("자동전표처리 [신용카드] 열기", open_credit_card)
        self.step("구분을 '2. 매입' 으로 변경", lambda: self.choose("구분", "2. 매입"))
        self.step("카드를 '전체거래처' 로 확인", check_all_cards)
        self.step("전표상태를 '전체' 로 변경", lambda: self.choose("전표상태", "전체"))
        self.step("[조회] 누르기", search)
        self.step("거래처 머리글 눌러 거래처별 정렬", sort_by_merchant)


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

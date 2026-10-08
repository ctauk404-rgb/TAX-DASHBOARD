"""위하고 카드 매입 표(RealGrid)에 값을 넣는다.

3차 조사 결과
- 표 객체는 React 컴포넌트의 _gridView. 카드 목록 표는 ty_jungstat 칸이 있는 표다.
- 화면 '유형' = ty_mth2, '차변계정' = cd_acctit_cha / nm_acctit_cha.
- 사용자가 칸을 고치면 위하고가 곧바로 PUT /smarta/saac0105/6/{sq_sbook}/ 로 서버에 저장한다.

그래서 값을 직접 데이터에 써 넣지 않고, 사람이 하는 것과 똑같이
'그 칸으로 이동 → 키보드로 입력 → Enter' 를 한다. 저장 요청은 위하고가 스스로 보낸다.
"""

import time
from urllib.parse import urlsplit

_MAIN = """
const __main = () => (window.__wehagoAll || window.__wehagoGrids || []).find(g => {
  try { return g.columnByField('ty_jungstat') && g.getDataSource().getRowCount() > 0; }
  catch (e) { return false; }
});
"""

HAS_MAIN_JS = "() => {" + _MAIN + " return !!__main(); }"

LOCATE_JS = "(sq) => {" + _MAIN + """
  const g = __main(); if (!g) return null;
  const ds = g.getDataSource(), n = ds.getRowCount();
  for (let r = 0; r < n; r++) {
    if (String(ds.getValue(r, 'sq_sbook')) === String(sq)) return {row: r, item: g.getItemIndex(r)};
  }
  return null;
}"""

FOCUS_JS = "([item, field]) => {" + _MAIN + """
  const g = __main();
  g.setCurrent({itemIndex: item, column: field, fieldName: field});
  g.setFocus();
  const c = g.getCurrent();
  return c && c.itemIndex === item && (c.column === field || c.fieldName === field);
}"""

VALUE_JS = "([item, field]) => {" + _MAIN + """
  const v = __main().getValue(item, field);
  return v === null || v === undefined ? '' : String(v);
}"""

# 전표상태 칸이 화면에 글자를 어떻게 그리는지(코드 → 글자) 알아내기 위한 조사
STATUS_PROBE_JS = "() => {" + _MAIN + """
  const g = __main(); if (!g) return null;
  const out = {};
  try {
    const col = g.columnByField('ty_jungstat');
    for (const k of Object.keys(col || {})) {
      const v = col[k];
      out[k] = typeof v === 'function' ? String(v).slice(0, 1500)
             : (v && typeof v === 'object') ? Object.keys(v).slice(0, 30) : v;
    }
  } catch (e) { out.error = String(e); }
  return out;
}"""


# 화면 '거래처' 머리글을 누른 것과 같은 정렬
SORT_JS = "() => {" + _MAIN + """
  const g = __main();
  try { g.orderBy(['nm_trade'], ['ascending']); } catch (e) { g.orderBy(['nm_trade']); }
  return true;
}"""

# 왼쪽 체크칸: 모두 해제한 뒤 sq_sbook 목록의 줄만 체크
CHECK_JS = "(sqs) => {" + _MAIN + """
  const g = __main(), ds = g.getDataSource(), want = new Set(sqs.map(String)), items = [];
  for (let r = 0, n = ds.getRowCount(); r < n; r++) {
    if (want.has(String(ds.getValue(r, 'sq_sbook')))) items.push(g.getItemIndex(r));
  }
  try { g.checkAll(false, false, false, true); } catch (e) { try { g.checkAll(false); } catch (e2) {} }
  try { g.checkItems(items, true, true); }
  catch (e) { for (const i of items) g.checkItem(i, true, false, true); }
  if (items.length) g.setCurrent({itemIndex: Math.min(...items), column: 'nm_trade'});
  return {wanted: items.length, checked: (g.getCheckedItems() || []).length};
}"""

# 사용자가 화면에서 누른 버튼·글자와 뜬 창을 기록 (일괄변경 방법 조사용).
# 짧은 글자(버튼 이름 등)만 남기고 숫자는 가린다.
ACTION_LOG_JS = r"""
(() => {
  if (window.__wehagoActions) return;
  window.__wehagoActions = [];
  const text = el => {
    const t = (el && (el.innerText || el.value || el.title || '') || '').trim().replace(/\d/g, '#');
    return t.length <= 30 ? t : t.slice(0, 30) + '…';
  };
  const desc = el => el ? `${el.tagName.toLowerCase()}.${String(el.className || '').split(/\s+/).slice(0, 3).join('.')}` : '';
  document.addEventListener('click', e => {
    if (!window.__wehagoRecording) return;
    const btn = e.target.closest('button, a, li, [role=button], [role=menuitem], label, span') || e.target;
    window.__wehagoActions.push({type: 'click', el: desc(btn), text: text(btn)});
  }, true);
  document.addEventListener('keydown', e => {
    if (!window.__wehagoRecording) return;
    window.__wehagoActions.push({type: 'key', key: e.key.length === 1 ? (/\d/.test(e.key) ? '#' : '*') : e.key,
                                 ctrl: e.ctrlKey, shift: e.shiftKey});
  }, true);
  new MutationObserver(ms => {
    if (!window.__wehagoRecording) return;
    for (const m of ms) for (const n of m.addedNodes) {
      if (n.nodeType !== 1) continue;
      const cls = String(n.className || '');
      if (/dialog|popup|modal|alert|confirm|layer/i.test(cls)) {
        const buttons = [...n.querySelectorAll('button')].map(text).filter(Boolean).slice(0, 10);
        window.__wehagoActions.push({type: 'popup', el: desc(n), title: text(n.querySelector('h1,h2,h3,.title,.tit,strong')), buttons});
      }
    }
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
"""

# 값 칸 → 사람이 입력하는 화면 칸. 계정 코드 칸(cd_acctit_cha)은 숨어 있어서
# 화면의 '차변계정' 칸(nm_acctit_cha)에 계정 코드를 입력한다.
INPUT_COLUMN = {"ty_mth2": "ty_mth2", "cd_acctit_cha": "nm_acctit_cha"}


class GridEditor:
    def __init__(self, page):
        self.page = page
        self.frame = self._find_frame()

    def _find_frame(self):
        for frame in self.page.frames:
            try:
                if frame.evaluate(HAS_MAIN_JS):
                    return frame
            except Exception:
                pass
        raise LookupError("위하고 카드 매입 표를 찾지 못했습니다. [조회] 를 다시 눌러 주세요.")

    def sort_by_merchant(self):
        self.frame.evaluate(SORT_JS)

    def check(self, sqs):
        return self.frame.evaluate(CHECK_JS, [str(x) for x in sqs])

    def value(self, item, field):
        return self.frame.evaluate(VALUE_JS, [item, field])

    def edit(self, sq_sbook, field, typed, expect):
        """sq_sbook 건의 field 값을 바꾼다. 화면에 보이는 칸(INPUT_COLUMN)에 typed 를 입력하고
        field 값이 expect 가 되었는지 확인한다.

        돌려주는 값: (성공 여부, 입력 전 값, 입력 후 값, 메모)
        """
        loc = self.frame.evaluate(LOCATE_JS, sq_sbook)
        if not loc:
            return False, "", "", "표에서 이 건을 찾지 못함"
        item = loc["item"]
        before = self.value(item, field)
        if before == expect:
            return True, before, before, "이미 같은 값"
        if not self.frame.evaluate(FOCUS_JS, [item, INPUT_COLUMN.get(field, field)]):
            return False, before, before, "칸으로 이동하지 못함"
        self.page.wait_for_timeout(300)

        saved = []

        def on_response(r):
            if r.request.method == "PUT" and urlsplit(r.url).path.rstrip("/").endswith(f"/{sq_sbook}"):
                saved.append(r.status)

        self.page.on("response", on_response)
        try:
            self.page.keyboard.type(str(typed), delay=60)
            self.page.wait_for_timeout(400)
            self.page.keyboard.press("Enter")
            deadline = time.time() + 6
            after = before
            while time.time() < deadline:
                self.page.wait_for_timeout(300)
                after = self.value(item, field)
                if after == expect and saved:
                    break
        finally:
            self.page.remove_listener("response", on_response)

        if after != expect:
            self.page.keyboard.press("Escape")
            return False, before, after, "입력 후 값이 예상과 다름"
        if not saved:
            return False, before, after, "위하고 저장 요청이 확인되지 않음"
        if any(s >= 400 for s in saved):
            return False, before, after, f"위하고 저장 실패 (HTTP {saved})"
        return True, before, after, "저장됨"

    # ---- 거래처별 일괄변경 (recon5 로 확인한 위하고 방식) ----------------------
    # 같은 거래처 줄들을 체크 → 맨 위 줄 하나를 고침 → 하단 [일괄변경] → [확인]
    # → 위하고가 PUT /smarta/saac0105/batch/6/ 으로 체크된 줄 전체를 저장한다.
    def values(self, sqs, field):
        out = {}
        for sq in sqs:
            loc = self.frame.evaluate(LOCATE_JS, sq)
            out[str(sq)] = self.value(loc["item"], field) if loc else None
        return out

    def _visible_buttons(self, name):
        found = []
        for frame in self.page.frames:
            loc = frame.get_by_role("button", name=name, exact=True)
            for i in range(min(loc.count(), 10)):
                b = loc.nth(i)
                try:
                    if b.is_visible():
                        found.append(b)
                except Exception:
                    pass
        return found

    def _click_bulk_button(self):
        buttons = self._visible_buttons("일괄변경")
        if not buttons:
            raise LookupError("[일괄변경] 버튼을 찾지 못함")
        # 하단 일괄변경 = 화면에서 가장 아래 있는 것
        buttons.sort(key=lambda b: (b.bounding_box() or {"y": 0})["y"])
        buttons[-1].click()

    def _confirm_dialogs(self, wait_ms=2500):
        """일괄변경 후 뜨는 확인 창들을 [확인] 으로 닫는다. 닫은 횟수를 돌려준다."""
        clicked, deadline = 0, time.time() + wait_ms / 1000
        while time.time() < deadline and clicked < 3:
            buttons = self._visible_buttons("확인")
            if buttons:
                buttons[-1].click()
                clicked += 1
                self.page.wait_for_timeout(600)
                deadline = time.time() + 1.5
            else:
                self.page.wait_for_timeout(200)
        return clicked

    def bulk_edit(self, sqs, field, typed, expect):
        """sqs 건들의 field 를 한 번에 expect 로 바꾼다.

        돌려주는 값: {sq: (성공 여부, 입력 전 값, 입력 후 값, 메모)}
        """
        sqs = [str(s) for s in sqs]
        before = self.values(sqs, field)
        todo = [s for s in sqs if before[s] is not None and before[s] != expect]
        result = {s: (True, before[s], before[s], "이미 같은 값") for s in sqs if before[s] == expect}
        for s in sqs:
            if before[s] is None:
                result[s] = (False, "", "", "표에서 이 건을 찾지 못함")
        if not todo:
            return result
        if len(todo) == 1:
            result[todo[0]] = self.edit(todo[0], field, typed, expect)
            return result

        checked = self.check(todo)
        if checked.get("checked") != len(todo):
            raise RuntimeError(f"체크 실패 ({checked})")
        head = todo[0]
        ok, b, a, memo = self.edit(head, field, typed, expect)
        if not ok:
            for s in todo:
                result[s] = (False, before[s], b if s == head else before[s], f"첫 줄 입력 실패: {memo}")
            return result

        # 고친 칸에 커서를 다시 두고 일괄변경
        loc = self.frame.evaluate(LOCATE_JS, head)
        self.frame.evaluate(FOCUS_JS, [loc["item"], INPUT_COLUMN.get(field, field)])
        self.page.wait_for_timeout(300)
        batch = []

        def on_response(r):
            if r.request.method == "PUT" and "/saac0105/batch/" in urlsplit(r.url).path:
                batch.append(r.status)

        self.page.on("response", on_response)
        try:
            self._click_bulk_button()
            self._confirm_dialogs()
            deadline = time.time() + 8
            while time.time() < deadline and not batch:
                self.page.wait_for_timeout(300)
            self.page.wait_for_timeout(1500)  # 위하고가 바뀐 줄을 다시 불러오는 시간
        finally:
            self.page.remove_listener("response", on_response)

        after = self.values(todo, field)
        status = "일괄변경 저장됨" if batch and all(s < 400 for s in batch) else f"일괄변경 저장 확인 안 됨 {batch}"
        for s in todo:
            done = after[s] == expect
            result[s] = (done and bool(batch), before[s], after[s] or "", status if done else "일괄변경 후 값이 예상과 다름")
        try:
            self.check([])  # 체크 해제
        except Exception:
            pass
        return result

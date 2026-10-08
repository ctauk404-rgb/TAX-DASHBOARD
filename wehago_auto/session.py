"""자동 입력(apply)과 원복(undo).

순서: 로그인(사용자) → 화면 이동 → 목록 읽기 → 미리보기 → 대상 확인 → 1건 시험 → 나머지
- 전표전송은 하지 않는다. 입력이 끝나면 세무사님이 위하고에서 확인하고 직접 전송한다.
- 바꾸기 전 값을 원복_*.csv 에 남겨서 undo 로 되돌릴 수 있게 한다.
"""

import csv
import json
import time
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

import codes as codes_mod
import store
from classifier import load_rules, load_settings
from grid import HAS_MAIN_JS, STATUS_PROBE_JS, GridEditor
from plan import Accounts, build_changes
from preview import build_groups, render
from wehago import _GRID_JS, CARD_LIST_PATH, GRID_HOOK_JS, SkipClient, Wehago, launch

ACCOUNT_HELP_PATH = "/smarta/codehelp/acctcd/"
LOG_FIELDS = ["시각", "수임처", "sq_sbook", "거래처", "field", "칸", "입력 전", "입력 후", "결과", "메모"]


def ask_yes(question):
    return input(f"{question} (y/N): ").strip().lower() in ("y", "yes", "ㅛ")


class Run:
    """브라우저를 열고, 로그인 후 수임처별 카드 매입 목록을 연다."""

    def __init__(self, p, client=None):
        self.client = client
        self.browser = launch(p)
        self.context = self.browser.new_context(viewport={"width": 1600, "height": 900})
        self.context.add_init_script(GRID_HOOK_JS)
        self.lists, self.account_help = [], []
        self.context.on("response", self._on_response)
        self.w = Wehago(self.context)
        self.home = None

    def _on_response(self, r):
        path = urlsplit(r.url).path
        if path == CARD_LIST_PATH and r.request.method == "POST":
            self.lists.append(r)
        elif path == ACCOUNT_HELP_PATH:
            self.account_help.append(r)

    def login(self):
        self.w.wait_login()
        self.home = (self.w.page, self.w.page.url)  # 수임처 목록 화면

    def back_home(self):
        """다음 수임처를 위해 수임처 목록 화면으로 돌아간다."""
        page, url = self.home
        for other in list(self.context.pages):
            if other is not page:
                try:
                    other.close()
                except Exception:
                    pass
        self.w.page = page
        if page.url != url:
            page.goto(url)
        page.wait_for_timeout(1500)

    def open_client(self, client, ask=True):
        """수임처의 카드 매입 목록을 열고 표가 뜰 때까지 기다린다."""
        self.client = client
        self.lists.clear()
        self.w.log = []
        self.w.open_card_purchase_list(client, load_settings().get("period_from"))
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.lists and (self._grid_ready() or self._list_empty()):
                return
            self.w.page.wait_for_timeout(500)
        if ask:
            input("\n카드 매입 내역 표가 화면에 보이면 Enter를 누르세요...")
        if not self._grid_ready() and not self._list_empty():
            raise RuntimeError("카드 매입 표를 찾지 못했습니다")

    def _list_empty(self):
        """조회는 됐는데 카드 매입 내역이 0건인 경우."""
        try:
            return bool(self.lists) and not self.lists[-1].json().get("data")
        except Exception:
            return False

    def _grid_ready(self):
        ready = False
        for frame in self.w.page.frames:  # 표 객체를 찾아 window.__wehagoAll 에 기억
            try:
                frame.evaluate(_GRID_JS)
                ready = ready or frame.evaluate(HAS_MAIN_JS)
            except Exception:
                pass
        return ready

    def open(self):
        self.login()
        self.open_client(self.client)

    def data(self):
        for _ in range(2):
            if self.lists:
                try:
                    return self.lists[-1].json().get("data", [])
                except Exception:
                    pass
            input("카드 목록을 읽지 못했습니다. 위하고에서 [조회] 를 한 번 더 누르고 Enter를 누르세요...")
        raise RuntimeError("카드 목록 데이터를 읽지 못했습니다.")

    def accounts(self, data):
        helps = []
        for r in self.account_help[-1:]:
            try:
                helps = r.json()
            except Exception:
                pass
        return Accounts(data, helps if isinstance(helps, list) else [])


def choose_states(rows, settings):
    counts = Counter(r["전표상태코드"] for r in rows)
    preset = {str(s) for s in settings.get("editable_states") or []}
    print("\n전표상태 코드별 건수:")
    for code, n in counts.most_common():
        print(f"  코드 {code}: {n}건  ({rows_label(rows, code)})")
    if preset:
        print(f"settings.json 에 정해 둔 자동 입력 대상: {', '.join(sorted(preset))}")
        return preset
    print("※ 이미 전표전송된 상태는 반드시 빼 주세요. 확정가능·미추천 등 아직 전송 전인 상태만 고릅니다.")
    picked = input("자동 입력할 전표상태 코드를 쉼표로 입력하세요 (예: 1,3): ")
    return {s.strip() for s in picked.split(",") if s.strip()}


def rows_label(rows, code):
    names = Counter(r["차변계정"] for r in rows if r["전표상태코드"] == code).most_common(2)
    return "차변계정 예: " + ", ".join(n for n, _ in names)


def write_log(path, row):
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def _log(log_path, client, ch, sq, success, before, after, memo):
    write_log(log_path, {
        "시각": datetime.now().strftime("%H:%M:%S"), "수임처": client,
        "sq_sbook": sq, "거래처": ch["거래처"], "field": ch["field"], "칸": ch["칸"],
        "입력 전": before, "입력 후": after, "결과": "성공" if success else "실패", "메모": memo,
    })


def batches(changes):
    """같은 거래처·같은 칸·같은 값으로 바꾸는 건끼리 묶는다 (입력 순서 유지)."""
    from classifier import normalize

    out = {}
    for ch in changes:
        out.setdefault((normalize(ch["거래처"]), ch["field"], ch["expect"]), []).append(ch)
    return list(out.values())


FIELD_LABEL = {"ty_mth2": "유형", "cd_acctit_cha": "차변계정"}


def run_changes(editor, changes, log_path, client, bulk=True, done=None):
    """변경을 적용한다. bulk 이면 거래처별로 묶어 위하고 [일괄변경] 을 쓴다.
    done 을 주면 성공한 건을 {sq: {'유형'|'차변계정': 값}} 로 모은다."""
    ok = fail = streak = 0
    groups = batches(changes) if bulk else [[c] for c in changes]
    for i, group in enumerate(groups, 1):
        ch = group[0]
        sqs = [str(c["sq_sbook"]) for c in group]
        try:
            if len(group) == 1:
                results = {sqs[0]: editor.edit(sqs[0], ch["field"], ch["typed"], ch["expect"])}
            else:
                results = editor.bulk_edit(sqs, ch["field"], ch["typed"], ch["expect"])
        except Exception as e:
            print(f"  일괄변경 실패 ({e}) → 한 건씩 입력합니다")
            results = {sq: editor.edit(sq, ch["field"], ch["typed"], ch["expect"]) for sq in sqs}
        good = 0
        for c in group:
            success, before, after, memo = results[str(c["sq_sbook"])]
            _log(log_path, client, c, c["sq_sbook"], success, before, after, memo)
            good += success
            if success and done is not None:
                done.setdefault(str(c["sq_sbook"]), {})[FIELD_LABEL[c["field"]]] = c["후"]
        mark = "✔" if good == len(group) else "✘"
        print(f"  [{i}/{len(groups)}] {mark} {ch['거래처']} · {ch['칸']} {ch['전']} → {ch['후']}"
              f" ({good}/{len(group)}건)")
        ok, fail = ok + good, fail + len(group) - good
        streak = 0 if good else streak + 1
        if streak >= 3:
            print("\n연속 3번 실패해서 멈춥니다. 위하고 화면 상태를 확인해 주세요.")
            break
    return ok, fail


def prepare(run, client, settings, rules, out_dir, stamp, states=None, open_preview=True):
    """목록 읽기 → 기록 저장 → 과거 판단 → 미리보기 → 변경 목록."""
    data = run.data()
    codes, _ = codes_mod.merge_grid_labels([])
    rows = [codes_mod.to_row(d, codes) for d in data]
    st = store.load()
    store.update(st, client, rows)
    store.save(st)
    if states is None:
        states = choose_states(rows, settings)

    # 과거(처리된) 전표의 거래처별 유형: 이번 기간 외에 이전 실행에서 쌓인 기록도 포함
    processed = {r["전표상태코드"] for r in st[client].values()} - states
    history = store.past_types(st, client, processed)
    n_general = sum(1 for c in history.values() if c.get("일반", 0) * 2 >= sum(c.values()))
    print(f"과거 전표 기록: 거래처 {len(history)}곳 (그중 일반 {n_general}곳 → 이번에도 일반)")

    groups = build_groups(rows, client, rules, settings, history)
    preview_path = Path(out_dir) / f"미리보기_{client}_{stamp}.html"
    preview_path.write_text(render(client, rows, groups, "코드 표시값 일부 추정"), encoding="utf-8")
    if open_preview:
        webbrowser.open(preview_path.resolve().as_uri())
    print(f"미리보기: {preview_path}")

    changes, skipped = build_changes(rows, client, rules, settings, run.accounts(data), states, history)
    # 유형부터: 유형이 바뀌면 위하고가 계정을 다시 추천할 수 있어서
    changes.sort(key=lambda c: (c["field"] != "ty_mth2", str(c["sq_sbook"])))
    print(f"입력할 변경: {len(changes)}건 "
          f"(유형 {sum(c['field'] == 'ty_mth2' for c in changes)}, "
          f"차변계정 {sum(c['field'] == 'cd_acctit_cha' for c in changes)})")
    print("건너뜀: " + (", ".join(f"{k} {v}건" for k, v in skipped.items()) or "없음"))
    return st, rows, states, changes, skipped


def trial_and_rest(editor, changes, log_path, client, done, ask_rest=True):
    """거래처 하나로 시험 → (확인 후) 나머지. 돌려주는 값: (성공, 실패, 계속 진행 여부)"""
    groups = batches(changes)
    trial = next((g for g in groups if len(g) >= 2), groups[0])
    t = trial[0]
    if not ask_yes(f"\n먼저 거래처 하나만 시험으로 입력해 볼까요? [{client} · {t['거래처']} {len(trial)}건 · "
                   f"{t['칸']} {t['전']} → {t['후']}]"):
        return 0, 0, False
    ok, fail = run_changes(editor, trial, log_path, client, done=done)
    if not ok:
        print("시험 입력이 실패했습니다. 화면을 그대로 두고 Claude에게 결과를 알려 주세요.")
        return ok, fail, False
    print("위하고 화면에서 그 거래처의 값과 전표상태를 확인해 보세요.")
    rest = [c for c in changes if c not in trial]
    if ask_rest and not ask_yes(f"나머지 {len(rest)}건도 입력할까요?"):
        return ok, fail, False
    ok2, fail2 = run_changes(editor, rest, log_path, client, done=done)
    return ok + ok2, fail + fail2, True


def apply_session(client, out_dir="."):
    out_dir = Path(out_dir)
    settings, rules = load_settings(), load_rules()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    with sync_playwright() as p:
        run = Run(p, client)
        run.open()
        editor = GridEditor(run.w.page)
        st, rows, states, changes, _ = prepare(run, client, settings, rules, out_dir, stamp)

        # 전표상태 조사 (다음 개선용, 글자 표시 방식만 기록)
        probe = editor.frame.evaluate(STATUS_PROBE_JS)
        (out_dir / "recon4_결과.json").write_text(
            json.dumps({"status_column": probe,
                        "status_counts": Counter(r["전표상태코드"] for r in rows)},
                       ensure_ascii=False, indent=1), encoding="utf-8")

        if not changes:
            finish_report(st)
            input("입력할 것이 없습니다. Enter를 누르면 끝납니다...")
            return
        done = {}
        log_path = out_dir / f"원복_{client}_{stamp}.csv"
        editor.sort_by_merchant()  # 화면 '거래처' 머리글 클릭과 같은 정렬
        ok, fail, _ = trial_and_rest(editor, changes, log_path, client, done)
        print(f"\n완료: 성공 {ok}건, 실패 {fail}건. 기록: {log_path}")
        store.apply_results(st, client, done)
        store.save(st)
        finish_report(st)
        print("\n전표전송은 하지 않았습니다. 위하고에서 확인하신 뒤 직접 전송해 주세요.")
        print(f"되돌리려면: undo.bat {log_path.name}")
        input("이 창에서 확인을 마치셨으면 Enter를 누르세요 (브라우저가 닫힙니다)...")


def read_clients(path="수임처목록.txt"):
    path = Path(path)
    if path.exists():
        names = [l.strip() for l in path.read_text(encoding="utf-8-sig").splitlines()]
        names = [n for n in names if n and not n.startswith("#")]
        if names:
            return names
    typed = input("처리할 수임처 이름을 쉼표로 입력하세요 (예: 팔각도, 글로벌에스에이치): ")
    return [n.strip() for n in typed.split(",") if n.strip()]


BATCH_FIELDS = ["수임처", "결과", "전체 건수", "입력할 변경", "성공", "실패", "건너뜀", "원복 파일", "메모"]


def batch_session(clients, out_dir="."):
    """여러 수임처를 한 번 로그인으로 차례대로 처리한다.

    - 자동 입력할 전표상태는 첫 수임처에서 한 번만 고른다 (settings.json 에 있으면 그대로)
    - 시험(거래처 하나)은 처음 변경이 있는 수임처에서 한 번만 하고, 그 뒤는 자동으로 진행
    - 수임처 하나가 실패해도 기록하고 다음 수임처로 넘어간다
    """
    out_dir = Path(out_dir)
    settings, rules = load_settings(), load_rules()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    summary_path = out_dir / f"일괄처리결과_{stamp}.csv"
    states = {str(s) for s in settings.get("editable_states") or []} or None
    trial_done = False
    print(f"처리할 수임처 {len(clients)}곳: {', '.join(clients)}")

    with sync_playwright() as p:
        run = Run(p)
        run.login()
        for n, client in enumerate(clients, 1):
            print(f"\n{'=' * 60}\n[{n}/{len(clients)}] {client}\n{'=' * 60}")
            row = {"수임처": client, "결과": "", "전체 건수": "", "입력할 변경": "", "성공": 0, "실패": 0,
                   "건너뜀": "", "원복 파일": "", "메모": ""}
            try:
                run.open_client(client)
                st, rows, states, changes, skipped = prepare(
                    run, client, settings, rules, out_dir, stamp, states, open_preview=False)
                row.update({"전체 건수": len(rows), "입력할 변경": len(changes),
                            "건너뜀": ", ".join(f"{k} {v}" for k, v in skipped.items())})
                if changes:
                    done = {}
                    log_path = out_dir / f"원복_{client}_{stamp}.csv"
                    row["원복 파일"] = log_path.name
                    editor = GridEditor(run.w.page)
                    editor.sort_by_merchant()
                    if not trial_done:
                        ok, fail, go = trial_and_rest(editor, changes, log_path, client, done,
                                                      ask_rest=True)
                        trial_done = go
                        if not go:
                            row.update({"성공": ok, "실패": fail, "결과": "중단"})
                            store.apply_results(st, client, done)
                            store.save(st)
                            _write_row(summary_path, row)
                            print("시험 단계에서 멈췄습니다. 남은 수임처는 처리하지 않습니다.")
                            break
                    else:
                        ok, fail = run_changes(editor, changes, log_path, client, done=done)
                    store.apply_results(st, client, done)
                    store.save(st)
                    row.update({"성공": ok, "실패": fail})
                row["결과"] = "완료" if not row["실패"] else "일부 실패"
            except SkipClient as e:
                row.update({"결과": "건너뜀", "메모": str(e)})
            except Exception as e:
                row.update({"결과": "오류", "메모": f"{type(e).__name__}: {e}"})
                print(f"  오류로 이 수임처는 넘어갑니다: {e}")
            _write_row(summary_path, row)
            print(f"  → {row['결과']} (성공 {row['성공']}, 실패 {row['실패']})")
            if n < len(clients):
                try:
                    run.back_home()
                except Exception as e:
                    input(f"수임처 목록 화면으로 돌아가지 못했습니다 ({e}). 직접 수임처 목록을 열고 Enter...")
                    run.w.page = run.context.pages[-1]
                    run.home = (run.w.page, run.w.page.url)

        finish_report(store.load())
        print(f"\n수임처별 결과: {summary_path}")
        print("전표전송은 하지 않았습니다. 수임처별로 확인하신 뒤 직접 전송해 주세요.")
        input("Enter를 누르면 브라우저가 닫힙니다...")


def _write_row(path, row):
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=BATCH_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def finish_report(st):
    from report import make_report

    html_path, csv_path = make_report(st)
    webbrowser.open(html_path.resolve().as_uri())
    print(f"\n수임처별·거래처별 일반/카과 현황: {html_path} (엑셀용 {csv_path.name})")


def undo_session(log_file, out_dir="."):
    log_file = Path(log_file)
    with open(log_file, encoding="utf-8-sig", newline="") as f:
        done = [r for r in csv.DictReader(f)
                if r["결과"] == "성공" and r["입력 전"] and r["입력 전"] != r["입력 후"]]
    if not done:
        print("되돌릴 기록이 없습니다.")
        return
    client = done[0]["수임처"]
    changes = [{"sq_sbook": r["sq_sbook"], "거래처": r["거래처"], "field": r["field"], "칸": r["칸"],
                "typed": r["입력 전"], "expect": r["입력 전"], "전": r["입력 후"], "후": r["입력 전"]}
               for r in reversed(done)]
    print(f"{client}: {len(changes)}건을 입력 전 값으로 되돌립니다.")
    with sync_playwright() as p:
        run = Run(p, client)
        run.open()
        editor = GridEditor(run.w.page)
        out = Path(out_dir) / f"원복실행_{log_file.stem}.csv"
        ok, fail = run_changes(editor, changes, out, client, bulk=False)
        print(f"\n되돌리기 완료: 성공 {ok}건, 실패 {fail}건. 기록: {out}")
        input("Enter를 누르면 브라우저가 닫힙니다...")


def bulk_recon_session(client, out_dir="."):
    """정렬 + 같은 거래처 체크까지 프로그램이 하고, 일괄변경은 사용자가 직접 하면서 기록한다."""
    from classifier import normalize
    from grid import ACTION_LOG_JS
    from wehago import body_shape, diff_snapshots, _SNAPSHOT_JS, SNAPSHOT_FIELDS

    out_dir = Path(out_dir)
    result = {}
    with sync_playwright() as p:
        run = Run(p, client)
        run.context.add_init_script(ACTION_LOG_JS)
        run.open()
        data = run.data()
        editor = GridEditor(run.w.page)

        try:
            editor.sort_by_merchant()
            result["sort"] = "ok"
        except Exception as e:
            result["sort"] = f"error: {e}"
        result["sort_ok_by_user"] = ask_yes("\n표가 거래처 이름순으로 정렬되었나요?")

        # 같은 거래처가 2건 이상이고 아직 전송 전으로 보이는 거래처 하나를 고른다
        groups = {}
        for d in data:
            groups.setdefault(normalize(d.get("nm_trade")), []).append(d)
        candidates = sorted((g for g in groups.values() if len(g) >= 2), key=len)
        target = candidates[len(candidates) // 2] if candidates else []
        if target:
            name = target[0].get("nm_trade")
            try:
                result["check"] = editor.check([d["sq_sbook"] for d in target])
            except Exception as e:
                result["check"] = f"error: {e}"
            print(f"\n'{name}' {len(target)}건을 체크해 두었습니다 (화면에서 그 거래처 위치로 이동).")
            result["check_ok_by_user"] = ask_yes("왼쪽 체크칸에 그 거래처 줄들이 모두 체크되었나요?")

        sent = []
        run.context.on("request", lambda r: sent.append(r) if r.resource_type in ("xhr", "fetch") else None)
        before = [s for f in run.w.page.frames for s in _safe(f, _SNAPSHOT_JS, SNAPSHOT_FIELDS)]
        for f in run.w.page.frames:
            _safe(f, "() => { window.__wehagoRecording = true; window.__wehagoTrace = {}; }")
        print("\n이제 평소 하시는 대로 [일괄변경] 을 해 주세요.")
        print("  - 체크가 안 됐으면 직접 같은 거래처 줄들을 체크하셔도 됩니다")
        print("  - 실제로 맞는 값으로 바꾸시면 됩니다 (전표전송은 누르지 마세요)")
        input("일괄변경이 끝나면 Enter를 누르세요...")
        after = [s for f in run.w.page.frames for s in _safe(f, _SNAPSHOT_JS, SNAPSHOT_FIELDS)]
        result["actions"] = [a for f in run.w.page.frames for a in _safe(f, "() => window.__wehagoActions || []")]
        result["trace"] = [t for f in run.w.page.frames for t in [_safe(f, "() => window.__wehagoTrace", None)] if t]
        result["requests"] = [{"method": r.method, "path": urlsplit(r.url).path,
                               "body": body_shape(r) if r.method != "GET" else None}
                              for r in sent if "/collect" not in r.url and "lpevent" not in r.url][:60]
        result["changed"] = diff_snapshots(before, after)
        result["how_by_user"] = input("\n일괄변경을 어떻게 하셨는지 한 줄로 적어 주세요 (예: 상단 일괄변경 버튼 → 유형 선택 → 확인): ")

        out = out_dir / "recon5_결과.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        run.browser.close()
    print(f"\n조사 결과를 저장했습니다: {out}  — 이 파일을 Claude에게 보내 주세요.")


def _safe(frame, js, arg=None, default=()):
    try:
        out = frame.evaluate(js, arg) if arg is not None else frame.evaluate(js)
        return out if out is not None else default
    except Exception:
        return default

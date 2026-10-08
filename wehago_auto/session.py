"""자동 입력(apply)과 원복(undo).

순서: 로그인(사용자) → 화면 이동 → 목록 읽기 → 미리보기 → 대상 확인 → 1건 시험 → 나머지
- 전표전송은 하지 않는다. 입력이 끝나면 세무사님이 위하고에서 확인하고 직접 전송한다.
- 바꾸기 전 값을 원복_*.csv 에 남겨서 undo 로 되돌릴 수 있게 한다.
"""

import csv
import json
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

import codes as codes_mod
from classifier import load_rules, load_settings
from grid import STATUS_PROBE_JS, GridEditor
from plan import Accounts, build_changes
from preview import build_groups, render
from wehago import _GRID_JS, CARD_LIST_PATH, GRID_HOOK_JS, Wehago, launch

ACCOUNT_HELP_PATH = "/smarta/codehelp/acctcd/"
LOG_FIELDS = ["시각", "수임처", "sq_sbook", "거래처", "field", "칸", "입력 전", "입력 후", "결과", "메모"]


def ask_yes(question):
    return input(f"{question} (y/N): ").strip().lower() in ("y", "yes", "ㅛ")


class Run:
    """브라우저를 열고, 로그인 후 카드 매입 목록까지 연다."""

    def __init__(self, p, client):
        self.client = client
        self.browser = launch(p)
        self.context = self.browser.new_context(viewport={"width": 1600, "height": 900})
        self.context.add_init_script(GRID_HOOK_JS)
        self.lists, self.account_help = [], []
        self.context.on("response", self._on_response)
        self.w = Wehago(self.context)

    def _on_response(self, r):
        path = urlsplit(r.url).path
        if path == CARD_LIST_PATH and r.request.method == "POST":
            self.lists.append(r)
        elif path == ACCOUNT_HELP_PATH:
            self.account_help.append(r)

    def open(self):
        self.w.wait_login()
        self.w.open_card_purchase_list(self.client)
        input("\n카드 매입 내역 표가 화면에 보이면 Enter를 누르세요...")
        for frame in self.w.page.frames:  # 표 객체를 찾아 window.__wehagoAll 에 기억
            try:
                frame.evaluate(_GRID_JS)
            except Exception:
                pass

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


def run_changes(editor, changes, log_path, client):
    ok = fail = streak = 0
    for i, ch in enumerate(changes, 1):
        success, before, after, memo = editor.edit(ch["sq_sbook"], ch["field"], ch["typed"], ch["expect"])
        write_log(log_path, {
            "시각": datetime.now().strftime("%H:%M:%S"), "수임처": client,
            "sq_sbook": ch["sq_sbook"], "거래처": ch["거래처"], "field": ch["field"], "칸": ch["칸"],
            "입력 전": before, "입력 후": after, "결과": "성공" if success else "실패", "메모": memo,
        })
        mark = "✔" if success else "✘"
        print(f"  [{i}/{len(changes)}] {mark} {ch['거래처']} · {ch['칸']} {ch['전']} → {ch['후']} ({memo})")
        if success:
            ok, streak = ok + 1, 0
        else:
            fail, streak = fail + 1, streak + 1
            if streak >= 3:
                print("\n연속 3건 실패해서 멈춥니다. 위하고 화면 상태를 확인해 주세요.")
                break
    return ok, fail


def apply_session(client, out_dir="."):
    out_dir = Path(out_dir)
    settings, rules = load_settings(), load_rules()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    with sync_playwright() as p:
        run = Run(p, client)
        run.open()
        data = run.data()
        editor = GridEditor(run.w.page)

        # 미리보기
        codes, _ = codes_mod.merge_grid_labels([])
        rows = [codes_mod.to_row(d, codes) for d in data]
        groups = build_groups(rows, client, rules, settings)
        report = out_dir / f"미리보기_{client}_{stamp}.html"
        report.write_text(render(client, rows, groups, "코드 표시값 일부 추정"), encoding="utf-8")
        webbrowser.open(report.resolve().as_uri())
        print(f"\n미리보기를 열었습니다: {report}")

        # 전표상태 조사 (다음 개선용, 글자 표시 방식만 기록)
        probe = editor.frame.evaluate(STATUS_PROBE_JS)
        (out_dir / "recon4_결과.json").write_text(
            json.dumps({"status_column": probe,
                        "status_counts": Counter(r["전표상태코드"] for r in rows)},
                       ensure_ascii=False, indent=1), encoding="utf-8")

        states = choose_states(rows, settings)
        changes, skipped = build_changes(rows, client, rules, settings, run.accounts(data), states)
        print(f"\n입력할 변경: {len(changes)}건 "
              f"(유형 {sum(c['field'] == 'ty_mth2' for c in changes)}, "
              f"차변계정 {sum(c['field'] == 'cd_acctit_cha' for c in changes)})")
        print("건너뜀: " + ", ".join(f"{k} {v}건" for k, v in skipped.items()))
        if not changes:
            input("입력할 것이 없습니다. Enter를 누르면 끝납니다...")
            return

        log_path = out_dir / f"원복_{client}_{stamp}.csv"
        # 유형부터: 유형이 바뀌면 위하고가 계정을 다시 추천할 수 있어서
        changes.sort(key=lambda c: (c["field"] != "ty_mth2", str(c["sq_sbook"])))
        if not ask_yes(f"\n먼저 1건만 시험으로 입력해 볼까요? [{changes[0]['거래처']} · "
                       f"{changes[0]['칸']} {changes[0]['전']} → {changes[0]['후']}]"):
            return
        ok, _ = run_changes(editor, changes[:1], log_path, client)
        if not ok:
            print("시험 입력이 실패했습니다. 화면을 그대로 두고 Claude에게 결과를 알려 주세요.")
            input("Enter를 누르면 끝납니다...")
            return
        print("위하고 화면에서 그 건의 값과 전표상태를 확인해 보세요.")
        if ask_yes(f"나머지 {len(changes) - 1}건도 입력할까요?"):
            ok2, fail = run_changes(editor, changes[1:], log_path, client)
            print(f"\n완료: 성공 {ok + ok2}건, 실패 {fail}건. 기록: {log_path}")
        print("\n전표전송은 하지 않았습니다. 위하고에서 확인하신 뒤 직접 전송해 주세요.")
        print(f"되돌리려면: undo.bat {log_path.name}")
        input("이 창에서 확인을 마치셨으면 Enter를 누르세요 (브라우저가 닫힙니다)...")


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
        ok, fail = run_changes(editor, changes, out, client)
        print(f"\n되돌리기 완료: 성공 {ok}건, 실패 {fail}건. 기록: {out}")
        input("Enter를 누르면 브라우저가 닫힙니다...")

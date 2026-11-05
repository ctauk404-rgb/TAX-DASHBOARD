"""수임처별 · 거래처별 일반/카과 현황표 (data/기록.json 기준)."""

import csv
import html
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from classifier import normalize


def summarize(store):
    """{수임처: [거래처 요약, ...]}"""
    out = {}
    for client, book in sorted(store.items()):
        groups = defaultdict(list)
        for r in book.values():
            groups[normalize(r["거래처"])].append(r)
        rows = []
        for items in groups.values():
            label = lambda t: "공제" if t in ("카과", "현과") else t
            types = Counter(label(r["유형"]) for r in items)
            amounts = Counter()
            for r in items:
                amounts[label(r["유형"])] += r.get("합계") or 0
            main = types.most_common(1)[0][0]
            rows.append({
                "거래처": items[0]["거래처"],
                "구분": ", ".join(sorted({r.get("구분", "") for r in items} - {""})),
                "판정": main if len(types) == 1 else f"{main} (혼재)",
                "자료": ", ".join(sorted({r.get("자료", "신용카드") for r in items})),
                "일반 건수": types.get("일반", 0), "공제 건수": types.get("공제", 0),
                "일반 금액": amounts.get("일반", 0), "공제 금액": amounts.get("공제", 0),
                "기타": ", ".join(f"{k} {v}" for k, v in types.items() if k not in ("일반", "공제")),
                "차변계정": ", ".join(k for k, _ in Counter(r["차변계정"] for r in items).most_common(2)),
                "기간": f'{min(r.get("일자", "") for r in items)} ~ {max(r.get("일자", "") for r in items)}',
            })
        rows.sort(key=lambda r: (r["판정"].startswith("공제"), r["거래처"]))
        out[client] = rows
    return out


COLUMNS = ["거래처", "자료", "구분", "판정", "일반 건수", "공제 건수", "일반 금액", "공제 금액", "기타", "차변계정",
           "기간"]


def write_csv(summary, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["수임처"] + COLUMNS)
        for client, rows in summary.items():
            for r in rows:
                w.writerow([client] + [r[c] for c in COLUMNS])


def render(summary):
    e = lambda v: html.escape(str(v))
    num = lambda v: f"{v:,}" if isinstance(v, int) else e(v)
    sections = []
    for client, rows in summary.items():
        gen = sum(r["판정"].startswith("일반") for r in rows)
        body = "".join(
            f'<tr class="{"mix" if "혼재" in r["판정"] else ""}">'
            + "".join(f'<td class="{"n" if isinstance(r[c], int) else ""}">{num(r[c])}</td>' for c in COLUMNS)
            + "</tr>" for r in rows)
        sections.append(
            f'<section><h2>{e(client)}</h2><p class=note>거래처 {len(rows)}곳 · 일반 {gen}곳 · 공제(카과·현과) {len(rows) - gen}곳</p>'
            f'<table><thead><tr>{"".join(f"<th>{c}</th>" for c in COLUMNS)}</tr></thead><tbody>{body}</tbody></table></section>')
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>카드·현금영수증 매입 공제 현황</title>
<style>body{{font-family:"Malgun Gothic",sans-serif;margin:20px;color:#222;background:#fff}}
h1{{font-size:20px}} h2{{font-size:16px;margin:24px 0 4px}} .note{{color:#666;font-size:12px;margin:0}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}}
th,td{{border:1px solid #ddd;padding:4px 6px}} th{{background:#f3f4f6}} td.n{{text-align:right}}
tr.mix{{background:#fff4e5}}</style></head><body>
<h1>신용카드·현금영수증 매입 공제/일반 현황 (수임처별 · 거래처별)</h1>
<p class=note>{datetime.now():%Y-%m-%d %H:%M} 기준 · 주황색: 같은 거래처에 공제와 일반이 섞여 있음</p>
{"".join(sections)}</body></html>"""


def make_report(store, out_dir="."):
    summary = summarize(store)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = Path(out_dir) / f"현황_{stamp}.html"
    csv_path = Path(out_dir) / f"현황_{stamp}.csv"
    html_path.write_text(render(summary), encoding="utf-8")
    write_csv(summary, csv_path)
    return html_path, csv_path

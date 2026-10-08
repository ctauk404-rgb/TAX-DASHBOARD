"""분류 결과 미리보기 HTML. 위하고에는 아무것도 쓰지 않는다."""

import html
from collections import Counter
from datetime import datetime

from classifier import classify, group_by_merchant, parse_amount


def _e(v):
    return html.escape(str(v if v is not None else ""))


def build_groups(rows, client, rules, settings, history=None):
    groups = []
    for items in group_by_merchant(rows).values():
        decisions = [classify(r, client, rules, settings, history) for r in items]
        first = items[0]
        proposed_types = Counter(d.vat_type for d in decisions)
        proposed_accounts = Counter(d.account or "(미정)" for d in decisions)
        changes = sum(1 for r, d in zip(items, decisions)
                      if r["유형"] != d.vat_type or (d.account and r["차변계정"] != d.account))
        groups.append({
            "거래처": first["거래처"],
            "건수": len(items),
            "합계": sum(parse_amount(r.get("합계")) for r in items),
            "구분": ", ".join(sorted({r["구분"] for r in items})),
            "업종": f'{first.get("업태", "")} / {first.get("종목", "")}'.strip(" /"),
            "현재유형": ", ".join(f"{k}({v})" for k, v in Counter(r["유형"] for r in items).items()),
            "제안유형": ", ".join(f"{k}({v})" for k, v in proposed_types.items()),
            "현재계정": ", ".join(f"{k}({v})" for k, v in Counter(r["차변계정"] or "-" for r in items).items()),
            "제안계정": ", ".join(f"{k}({v})" for k, v in proposed_accounts.items()),
            "근거": " / ".join(sorted({d.reason for d in decisions})),
            "검토": any(d.review for d in decisions),
            "변경": changes,
        })
    groups.sort(key=lambda g: (not g["검토"], -g["변경"], g["거래처"]))
    return groups


def render(client, rows, groups, codes_note):
    status = Counter(r["전표상태"] for r in rows)
    total_changes = sum(g["변경"] for g in groups)
    reviews = sum(1 for g in groups if g["검토"])
    head = ["거래처", "건수", "합계", "구분", "업태/종목", "현재 유형", "제안 유형",
            "현재 차변계정", "제안 차변계정", "근거", "바뀌는 건"]
    body = []
    for g in groups:
        cls = "review" if g["검토"] else ("change" if g["변경"] else "")
        body.append(
            f'<tr class="{cls}"><td>{_e(g["거래처"])}</td><td class=n>{g["건수"]}</td>'
            f'<td class=n>{g["합계"]:,}</td><td>{_e(g["구분"])}</td><td>{_e(g["업종"])}</td>'
            f'<td>{_e(g["현재유형"])}</td><td><b>{_e(g["제안유형"])}</b></td>'
            f'<td>{_e(g["현재계정"])}</td><td><b>{_e(g["제안계정"])}</b></td>'
            f'<td>{_e(g["근거"])}</td><td class=n>{g["변경"]}</td></tr>')
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>카드 매입 분류 미리보기 - {_e(client)}</title>
<style>
body{{font-family:"Malgun Gothic",sans-serif;margin:20px;color:#222;background:#fff}}
h1{{font-size:20px}} .sum span{{display:inline-block;margin-right:18px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:12px}}
th,td{{border:1px solid #ddd;padding:4px 6px;vertical-align:top}} th{{background:#f3f4f6;position:sticky;top:0}}
td.n{{text-align:right}} tr.review{{background:#fff4e5}} tr.change{{background:#eef6ff}}
.note{{color:#666;font-size:12px}}
</style></head><body>
<h1>카드 매입 분류 미리보기 — {_e(client)}</h1>
<p class=note>{datetime.now():%Y-%m-%d %H:%M} · 이 화면은 미리보기입니다. 위하고에는 아무것도 바뀌지 않았습니다.</p>
<p class=sum><span>전체 <b>{len(rows)}</b>건</span><span>거래처 <b>{len(groups)}</b>곳</span>
<span>바뀔 건 <b>{total_changes}</b>건</span><span>검토 필요 거래처 <b>{reviews}</b>곳 (주황색)</span></p>
<p class=sum>전표상태: {_e(", ".join(f"{k} {v}건" for k, v in status.most_common()))}</p>
<p class=note>{_e(codes_note)}</p>
<table><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead>
<tbody>{"".join(body)}</tbody></table></body></html>"""

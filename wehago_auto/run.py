"""실행 진입점.

  python run.py recon --client 팔각도      위하고 화면 구조 조사 (읽기만 함)
  python run.py recon2 --client 팔각도     표 구조·저장 방식 조사 (한 건 수정 후 원복)
  python run.py preview --client 팔각도    분류 미리보기 (위하고에 쓰지 않음) + 3차 조사
  python run.py apply --client 팔각도      미리보기 → 1건 시험 → 유형·차변계정 자동 입력
  python run.py undo 원복_팔각도_xxx.csv   자동 입력한 값을 되돌리기
  python run.py plan rows.csv --client 팔각도   표 데이터(CSV)로 분류 결과 미리보기 (개발·점검용)
"""

import argparse
import csv
import sys

from classifier import classify, group_by_merchant, load_rules, load_settings


def cmd_recon(args):
    from wehago import recon

    client = args.client or input("작업할 수임처 이름: ").strip()
    recon(client, args.out)


def cmd_recon2(args):
    from wehago import recon2

    client = args.client or input("작업할 수임처 이름: ").strip()
    recon2(client, args.out)


def cmd_preview(args):
    from wehago import preview_session

    client = args.client or input("작업할 수임처 이름: ").strip()
    preview_session(client)


def cmd_apply(args):
    from session import apply_session

    client = args.client or input("작업할 수임처 이름: ").strip()
    apply_session(client)


def cmd_undo(args):
    from session import undo_session

    undo_session(args.log)


def cmd_plan(args):
    rules, settings = load_rules(), load_settings()
    with open(args.rows, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    writer = csv.writer(sys.stdout)
    writer.writerow(["거래처", "건수", "구분", "유형", "차변계정", "근거", "검토"])
    for group in group_by_merchant(rows).values():
        d = classify(group[0], args.client, rules, settings)
        writer.writerow([group[0]["거래처"], len(group), group[0].get("구분", ""),
                         d.vat_type, d.account or "(미정)", d.reason, "검토" if d.review else ""])


def main():
    parser = argparse.ArgumentParser(description="위하고 신용카드 매입 자동분류")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("recon", help="위하고 화면 구조 조사")
    p.add_argument("--client", help="수임처 이름 (예: 팔각도)")
    p.add_argument("--out", default="recon_결과.json")
    p.set_defaults(func=cmd_recon)

    p = sub.add_parser("recon2", help="표 구조와 저장 방식 조사")
    p.add_argument("--client", help="수임처 이름")
    p.add_argument("--out", default="recon2_결과.json")
    p.set_defaults(func=cmd_recon2)

    p = sub.add_parser("preview", help="분류 미리보기 + 3차 조사")
    p.add_argument("--client", help="수임처 이름")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("apply", help="미리보기 → 1건 시험 → 자동 입력 (전표전송은 안 함)")
    p.add_argument("--client", help="수임처 이름")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("undo", help="원복_*.csv 기록대로 되돌리기")
    p.add_argument("log")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("plan", help="CSV 로 분류 결과 미리보기")
    p.add_argument("rows")
    p.add_argument("--client", default="")
    p.set_defaults(func=cmd_plan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

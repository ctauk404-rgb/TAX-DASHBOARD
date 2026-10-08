"""위하고 카드 목록 데이터의 코드값 → 화면 표시값.

2차 조사(704건)의 코드별 건수로 추정한 값이다. 표 객체에서 실제 표시값 목록을
읽어 오면 그것으로 덮어쓴다 (merge_grid_labels).
- ty_biz 4 = 6건 = freetax 1 인 6건 → 면세
- 화면 '유형' 칸은 ty_mth2 (3차 조사에서 확인). 57 = 더존 매입매출 유형 카과,
  3 = 일반전표. ty_mth 는 숨은 '전표유형' 칸 (2 매입매출, 3 일반)
"""

TENTATIVE = {
    "ty_biz": {"1": "일반", "2": "법인", "3": "간이", "4": "면세"},   # 화면 '구분'
    "ty_mth2": {"3": "일반", "51": "과세", "52": "영세", "53": "면세", "54": "불공",
                "55": "수입", "57": "카과", "58": "카면", "59": "카영",
                "61": "현과", "62": "현면"},                          # 화면 '유형'
    "ty_jungstat": {},                                               # 화면 '전표상태' (미확인)
    "ty_gongjea": {"1": "공제", "2": "불공제"},                       # 화면 '국세청'
}


def merge_grid_labels(grids):
    """표 칸 정의(values/labels)가 있으면 그 값을 쓰고, 확인된 칸 이름을 돌려준다."""
    codes = {k: dict(v) for k, v in TENTATIVE.items()}
    confirmed = set()

    def walk(columns):
        for c in columns or []:
            walk(c.get("columns"))
            field = c.get("fieldName")
            values, labels = c.get("values"), c.get("labels")
            if field in codes and values and labels and len(values) == len(labels):
                codes[field] = {str(v): str(l) for v, l in zip(values, labels)}
                confirmed.add(field)

    for g in grids or []:
        if isinstance(g, dict):
            walk(g.get("columns"))
    return codes, confirmed


def label(codes, field, value):
    if value is None:
        return ""
    v = str(value)
    if v.endswith(".0"):
        v = v[:-2]
    return codes.get(field, {}).get(v, f"코드{v}")


def to_row(d, codes):
    """위하고 목록 데이터 한 건 → 분류기가 쓰는 한 줄."""
    return {
        "거래처": d.get("nm_trade") or "",
        "구분": label(codes, "ty_biz", d.get("ty_biz")),
        "업태": d.get("bizcond") or "",
        "종목": d.get("bizcate") or "",
        "공급가액": d.get("mn_mnam"),
        "세액": "" if d.get("mn_vat") is None else d.get("mn_vat"),
        "합계": d.get("mn_total"),
        "차변계정": d.get("nm_acctit_cha") or "",
        "유형": label(codes, "ty_mth2", d.get("ty_mth2")),
        "유형코드": str(d.get("ty_mth2") or ""),
        "계정코드": str(d.get("cd_acctit_cha") or ""),
        "전표상태코드": str(d.get("ty_jungstat") or ""),
        "sq_sbook": d.get("sq_sbook"),
        "전표상태": label(codes, "ty_jungstat", d.get("ty_jungstat")),
        "국세청": label(codes, "ty_gongjea", d.get("ty_gongjea")),
        "일자": d.get("da_sbook") or "",
    }

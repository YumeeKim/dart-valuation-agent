# -*- coding: utf-8 -*-
"""
3개년 데이터(당기/전기/전전기)를 이용한 규칙 기반 회계 이상징후 점검.
여기서 나온 결과는 '경고 신호 후보'이며, 최종 해석은 AI 에이전트가
업종 맥락과 함께 종합적으로 판단하도록 설계되어 있음(정답이 아닌 점검 리스트).
"""


def _growth(curr, prev):
    if curr is None or prev in (None, 0):
        return None
    return (curr - prev) / abs(prev)


def check_flags(three_year_items: dict) -> list:
    """반환: [{level, title, detail}, ...] 형태의 리스트"""
    flags = []
    t = three_year_items["thstrm"]
    p = three_year_items["frmtrm"]

    rev_g = _growth(t.get("revenue"), p.get("revenue"))
    ni_g = _growth(t.get("net_income"), p.get("net_income"))
    recv_g = _growth(t.get("receivables"), p.get("receivables"))
    inv_g = _growth(t.get("inventory"), p.get("inventory"))

    # 1) 매출채권 증가율이 매출 증가율을 큰 폭으로 초과 -> 매출 조기인식/부실채권 우려
    if rev_g is not None and recv_g is not None:
        if recv_g - rev_g > 0.15:
            flags.append({
                "level": "주의",
                "title": "매출채권 증가율 > 매출 증가율",
                "detail": f"매출채권 증가율({recv_g:.1%})이 매출 증가율({rev_g:.1%})보다 큰 폭으로 높습니다. "
                          f"매출 조기인식이나 채권 회수 지연 가능성을 점검할 필요가 있습니다.",
            })

    # 2) 재고자산 증가율이 매출 증가율을 큰 폭으로 초과 -> 재고 부실/수요 둔화 우려
    if rev_g is not None and inv_g is not None:
        if inv_g - rev_g > 0.20:
            flags.append({
                "level": "주의",
                "title": "재고자산 증가율 > 매출 증가율",
                "detail": f"재고자산 증가율({inv_g:.1%})이 매출 증가율({rev_g:.1%})보다 크게 높습니다. "
                          f"재고 진부화나 수요 둔화 가능성을 점검할 필요가 있습니다.",
            })

    # 3) 영업활동현금흐름/당기순이익(이익의 질) - 발생액 과다 여부
    cfo_ni = None
    if t.get("cfo") is not None and t.get("net_income") not in (None, 0):
        cfo_ni = t["cfo"] / t["net_income"]
        if t["net_income"] > 0 and cfo_ni < 0.5:
            flags.append({
                "level": "경고",
                "title": "영업현금흐름이 순이익 대비 현저히 낮음",
                "detail": f"영업활동현금흐름/당기순이익 비율이 {cfo_ni:.2f}로 낮습니다. "
                          f"장부상 이익은 나는데 실제 현금창출력이 뒷받침되지 않는 '이익의 질' 문제일 수 있습니다.",
            })
        if t["net_income"] > 0 and t["cfo"] is not None and t["cfo"] < 0:
            flags.append({
                "level": "경고",
                "title": "순이익은 흑자인데 영업현금흐름은 마이너스",
                "detail": "당기순이익은 플러스이나 영업활동현금흐름이 마이너스입니다. 이익의 실질성에 의문 부호가 붙는 전형적 패턴입니다.",
            })

    # 4) 매출 급감/급증 대비 순이익 방향이 반대 -> 일회성 손익 가능성
    if rev_g is not None and ni_g is not None:
        if rev_g > 0.05 and ni_g < -0.20:
            flags.append({
                "level": "주의",
                "title": "매출은 증가했는데 순이익은 큰 폭 감소",
                "detail": f"매출 증가율({rev_g:.1%}) 대비 순이익 증가율({ni_g:.1%})이 크게 낮습니다. "
                          f"일회성 비용, 손상차손, 마진 훼손 여부를 확인할 필요가 있습니다.",
            })

    # 5) 부채비율 급등
    debt_ratio_t = None
    debt_ratio_p = None
    if t.get("total_liabilities") is not None and t.get("total_equity"):
        debt_ratio_t = t["total_liabilities"] / t["total_equity"]
    if p.get("total_liabilities") is not None and p.get("total_equity"):
        debt_ratio_p = p["total_liabilities"] / p["total_equity"]
    if debt_ratio_t is not None and debt_ratio_p is not None and debt_ratio_p > 0:
        change = (debt_ratio_t - debt_ratio_p) / debt_ratio_p
        if change > 0.30:
            flags.append({
                "level": "주의",
                "title": "부채비율 급등",
                "detail": f"부채비율이 {debt_ratio_p:.1%} → {debt_ratio_t:.1%}로 전기 대비 크게 상승했습니다. "
                          f"차입 확대 배경(설비투자 vs 운영자금 부족)을 확인할 필요가 있습니다.",
            })

    # 6) 유동비율 100% 미만 -> 단기 유동성 우려
    if t.get("current_assets") and t.get("current_liabilities"):
        cr = t["current_assets"] / t["current_liabilities"]
        if cr < 1.0:
            flags.append({
                "level": "경고",
                "title": "유동비율 100% 미만",
                "detail": f"유동비율이 {cr:.1%}로 1년 내 갚아야 할 부채가 1년 내 현금화 가능한 자산보다 많습니다. "
                          f"단기 유동성 리스크를 점검할 필요가 있습니다.",
            })

    if not flags:
        flags.append({
            "level": "정상",
            "title": "규칙 기반 점검에서 뚜렷한 이상징후 없음",
            "detail": "단, 이는 제한된 정량 규칙 기반 점검이며 회계 부정을 완전히 배제하지 않습니다.",
        })

    return flags

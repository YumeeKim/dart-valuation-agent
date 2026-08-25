# -*- coding: utf-8 -*-
"""
DART 재무제표 DataFrame에서 필요한 계정과목 금액을 추출하고,
ROIC / WACC / PBR / PER / ROE 등 핵심 지표를 계산하는 모듈.

주의(v1 한계):
DART 재무제표는 회사마다 계정과목명이 조금씩 다르게 공시됩니다(K-IFRS 표준계정ID는
어느 정도 통일돼 있지만 100% 일관되진 않음). 아래는 account_id(IFRS 표준코드)를
1순위로, 계정명(account_nm) 텍스트 매칭을 2순위 fallback으로 사용하는 실용적 접근입니다.
값이 None이면 "해당 회사 공시에서 자동으로 못 찾은 항목"이라는 뜻이며,
결과 화면과 AI 프롬프트에 그 사실이 함께 전달됩니다.
"""
import re
import pandas as pd

# 1순위: IFRS 표준 계정ID 매칭
ACCOUNT_ID_MAP = {
    "total_assets": ["ifrs-full_Assets"],
    "total_liabilities": ["ifrs-full_Liabilities"],
    "total_equity": ["ifrs-full_Equity"],
    "current_assets": ["ifrs-full_CurrentAssets"],
    "current_liabilities": ["ifrs-full_CurrentLiabilities"],
    "cash": ["ifrs-full_CashAndCashEquivalents"],
    "inventory": ["ifrs-full_Inventories"],
    "receivables": ["ifrs-full_TradeAndOtherCurrentReceivables"],
    "revenue": ["ifrs-full_Revenue"],
    "operating_income": ["dart_OperatingIncomeLoss"],
    "net_income": ["ifrs-full_ProfitLoss"],
    "cfo": ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
}

# 2순위: 계정명 텍스트 fallback (account_nm에 포함되는 키워드)
ACCOUNT_NAME_KEYWORDS = {
    "total_assets": ["자산총계"],
    "total_liabilities": ["부채총계"],
    "total_equity": ["자본총계"],
    "current_assets": ["유동자산"],
    "current_liabilities": ["유동부채"],
    "cash": ["현금및현금성자산"],
    "inventory": ["재고자산"],
    "receivables": ["매출채권"],
    "revenue": ["매출액", "영업수익"],
    "operating_income": ["영업이익"],
    "net_income": ["당기순이익"],
    "cfo": ["영업활동현금흐름", "영업활동으로인한현금흐름"],
    "interest_expense": ["이자비용"],
}

# 이자부부채(차입금) 추정용 키워드 - 여러 줄을 합산
DEBT_KEYWORDS = ["단기차입금", "장기차입금", "유동성장기부채", "사채", "리스부채", "유동성사채"]
# 위 키워드에 걸리지만 실제 차입금이 아닌 항목은 제외
DEBT_EXCLUDE_KEYWORDS = ["매입채무", "충당부채"]


def _get_by_id(df: pd.DataFrame, ids: list, amount_col: str = "thstrm_amount"):
    if "account_id" not in df.columns:
        return None
    sub = df[df["account_id"].isin(ids)]
    if sub.empty:
        return None
    val = sub[amount_col].dropna()
    return float(val.iloc[0]) if not val.empty else None


def _get_by_name(df: pd.DataFrame, keywords: list, amount_col: str = "thstrm_amount"):
    if "account_nm" not in df.columns:
        return None
    mask = df["account_nm"].fillna("").apply(lambda x: any(k in x for k in keywords))
    sub = df[mask]
    if sub.empty:
        return None
    val = sub[amount_col].dropna()
    return float(val.iloc[0]) if not val.empty else None


def get_account(df: pd.DataFrame, key: str, amount_col: str = "thstrm_amount"):
    """account_id 우선, 없으면 account_nm 키워드로 fallback."""
    if df.empty:
        return None
    val = None
    if key in ACCOUNT_ID_MAP:
        val = _get_by_id(df, ACCOUNT_ID_MAP[key], amount_col)
    if val is None and key in ACCOUNT_NAME_KEYWORDS:
        val = _get_by_name(df, ACCOUNT_NAME_KEYWORDS[key], amount_col)
    return val


def estimate_interest_bearing_debt(df: pd.DataFrame, amount_col: str = "thstrm_amount"):
    """차입금 성격 계정을 이름 기반으로 합산 추정."""
    if df.empty or "account_nm" not in df.columns:
        return None
    mask = df["account_nm"].fillna("").apply(
        lambda x: any(k in x for k in DEBT_KEYWORDS) and not any(e in x for e in DEBT_EXCLUDE_KEYWORDS)
    )
    sub = df[mask]
    if sub.empty:
        return None
    total = sub[amount_col].dropna().sum()
    return float(total) if total else None


def extract_core_items(df: pd.DataFrame, amount_col: str = "thstrm_amount") -> dict:
    """한 시점(한 컬럼)에 대해 핵심 계정과목을 한번에 추출."""
    keys = [
        "total_assets", "total_liabilities", "total_equity",
        "current_assets", "current_liabilities", "cash", "inventory",
        "receivables", "revenue", "operating_income", "net_income",
        "cfo", "interest_expense",
    ]
    items = {k: get_account(df, k, amount_col) for k in keys}
    items["interest_bearing_debt"] = estimate_interest_bearing_debt(df, amount_col)
    return items


def extract_three_year_items(df: pd.DataFrame) -> dict:
    """DART 응답 한 번(사업보고서)에 포함된 당기/전기/전전기 3개년 데이터를 모두 추출."""
    return {
        "thstrm": extract_core_items(df, "thstrm_amount"),   # 당기
        "frmtrm": extract_core_items(df, "frmtrm_amount"),   # 전기
        "bfefrmtrm": extract_core_items(df, "bfefrmtrm_amount"),  # 전전기
    }


def safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def compute_financial_ratios(items: dict) -> dict:
    """당기 항목(dict)으로부터 기본 재무비율 계산."""
    r = {}
    r["operating_margin"] = safe_div(items.get("operating_income"), items.get("revenue"))
    r["net_margin"] = safe_div(items.get("net_income"), items.get("revenue"))
    r["roe"] = safe_div(items.get("net_income"), items.get("total_equity"))
    r["roa"] = safe_div(items.get("net_income"), items.get("total_assets"))
    r["debt_ratio"] = safe_div(items.get("total_liabilities"), items.get("total_equity"))
    r["current_ratio"] = safe_div(items.get("current_assets"), items.get("current_liabilities"))
    r["cfo_to_net_income"] = safe_div(items.get("cfo"), items.get("net_income"))  # 이익의 질(발생액 점검용)
    return r


def compute_roic(items: dict, tax_rate: float = 0.22):
    """ROIC = NOPAT / Invested Capital
    NOPAT = 영업이익 * (1 - 세율)
    Invested Capital = 자본총계 + 이자부부채 - 현금성자산 (단순화된 정의)
    """
    op_income = items.get("operating_income")
    equity = items.get("total_equity")
    debt = items.get("interest_bearing_debt") or 0
    cash = items.get("cash") or 0

    if op_income is None or equity is None:
        return None, None

    nopat = op_income * (1 - tax_rate)
    invested_capital = equity + debt - cash
    if invested_capital <= 0:
        return nopat, None
    return nopat, nopat / invested_capital


def compute_wacc(
    market_cap: float,
    interest_bearing_debt: float,
    interest_expense: float,
    risk_free_rate: float,
    beta: float,
    equity_risk_premium: float,
    tax_rate: float = 0.22,
):
    """WACC = E/V*Re + D/V*Rd*(1-Tc)
    Re(자기자본비용) = CAPM = Rf + Beta*ERP
    Rd(타인자본비용) = 이자비용 / 이자부부채 (실효 조달금리 근사치)
    market_cap(E), interest_bearing_debt(D) 가 0/None이면 계산 불가로 None 반환.
    """
    if market_cap is None or market_cap <= 0:
        return None

    debt = interest_bearing_debt or 0
    total_value = market_cap + debt
    if total_value <= 0:
        return None

    cost_of_equity = risk_free_rate + beta * equity_risk_premium

    if debt > 0 and interest_expense:
        cost_of_debt = interest_expense / debt
        # 비정상적으로 큰 값(회계상 왜곡) 방지용 캡
        cost_of_debt = min(cost_of_debt, 0.25)
    else:
        cost_of_debt = risk_free_rate + 0.015  # 부채/이자비용 데이터 없을 때의 보수적 근사치

    weight_equity = market_cap / total_value
    weight_debt = debt / total_value

    wacc = weight_equity * cost_of_equity + weight_debt * cost_of_debt * (1 - tax_rate)
    return {
        "wacc": wacc,
        "cost_of_equity": cost_of_equity,
        "cost_of_debt": cost_of_debt,
        "weight_equity": weight_equity,
        "weight_debt": weight_debt,
    }

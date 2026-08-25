# -*- coding: utf-8 -*-
"""
KRX 시장 데이터 조회 모듈 (pykrx 사용, API 키 불필요)
- 최근 영업일의 종가/시가총액/PER/PBR/BPS/EPS
- 최근 N일 수익률로 베타(시장민감도) 계산
"""
from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock

KOSPI_INDEX_CODE = "1001"
KOSDAQ_INDEX_CODE = "2001"


def _fmt(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def get_latest_trading_date(ticker: str, lookback_days: int = 15) -> str:
    """최근 영업일(데이터가 존재하는 날짜)을 YYYYMMDD 문자열로 반환."""
    today = datetime.now()
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        df = stock.get_market_ohlcv_by_date(_fmt(d), _fmt(d), ticker)
        if df is not None and not df.empty:
            return _fmt(d)
    raise RuntimeError("최근 거래일 데이터를 찾을 수 없습니다. (상장폐지/코드 오류 가능)")


def get_market_snapshot(ticker: str) -> dict:
    """현재가, 시가총액, 상장주식수, PER, PBR, EPS, BPS 스냅샷."""
    date = get_latest_trading_date(ticker)

    ohlcv = stock.get_market_ohlcv_by_date(date, date, ticker)
    cap = stock.get_market_cap_by_date(date, date, ticker)
    fund = stock.get_market_fundamental_by_date(date, date, ticker)

    if ohlcv.empty or cap.empty:
        raise RuntimeError("시세/시가총액 데이터를 가져오지 못했습니다.")

    close_price = int(ohlcv["종가"].iloc[0])
    market_cap = int(cap["시가총액"].iloc[0])
    shares_outstanding = int(cap["상장주식수"].iloc[0])

    per = pbr = eps = bps = None
    if not fund.empty:
        row = fund.iloc[0]
        per = float(row.get("PER")) if pd.notna(row.get("PER")) else None
        pbr = float(row.get("PBR")) if pd.notna(row.get("PBR")) else None
        eps = float(row.get("EPS")) if pd.notna(row.get("EPS")) else None
        bps = float(row.get("BPS")) if pd.notna(row.get("BPS")) else None

    return {
        "as_of": date,
        "close_price": close_price,
        "market_cap": market_cap,
        "shares_outstanding": shares_outstanding,
        "per_market": per,
        "pbr_market": pbr,
        "eps_market": eps,
        "bps_market": bps,
    }


def estimate_beta(ticker: str, years: int = 3, index_code: str = KOSPI_INDEX_CODE) -> float | None:
    """최근 N년 일간 수익률로 시장(코스피) 대비 베타를 추정 (단순 회귀 기울기).
    데이터가 부족하면 None 반환.
    """
    end = datetime.now()
    start = end - timedelta(days=365 * years + 10)

    stock_px = stock.get_market_ohlcv_by_date(_fmt(start), _fmt(end), ticker)
    index_px = stock.get_index_ohlcv_by_date(_fmt(start), _fmt(end), index_code)

    if stock_px.empty or index_px.empty:
        return None

    s_ret = stock_px["종가"].pct_change().dropna()
    i_ret = index_px["종가"].pct_change().dropna()

    merged = pd.concat([s_ret, i_ret], axis=1, join="inner")
    merged.columns = ["stock", "index"]
    merged = merged.dropna()

    if len(merged) < 60:  # 최소 표본 확보 안되면 신뢰 불가
        return None

    covariance = merged["stock"].cov(merged["index"])
    variance = merged["index"].var()
    if variance == 0:
        return None
    return float(covariance / variance)

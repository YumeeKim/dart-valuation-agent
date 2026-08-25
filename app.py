# -*- coding: utf-8 -*-
"""
OpenDART 기반 AI 가치평가 에이전트 (v1)

파이프라인: 기업명 입력 → OpenDART 재무제표 수집 → KRX 시장데이터 수집
           → ROIC/WACC/PBR 등 계산 → 규칙기반 회계 이상징후 점검
           → OpenAI로 종합 리포트 생성
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from modules import dart_client, market_data, financial_metrics, accounting_flags, ai_agent

st.set_page_config(page_title="AI 기업가치 평가 에이전트", page_icon="📊", layout="wide")

# ------------------------------------------------------------------
# API 키 로드: Streamlit Cloud의 Secrets(권장, 영구 고정)에서 우선 로드,
# 없으면 사이드바에서 세션 한정으로 임시 입력 가능
# ------------------------------------------------------------------
def get_api_keys():
    dart_key = st.secrets.get("DART_API_KEY", "") if hasattr(st, "secrets") else ""
    openai_key = st.secrets.get("OPENAI_API_KEY", "") if hasattr(st, "secrets") else ""

    with st.sidebar:
        st.header("⚙️ API 설정")
        if dart_key and openai_key:
            st.success("Secrets에서 API 키를 불러왔습니다. (앱 관리자가 이미 고정 설정함)")
        else:
            st.warning(
                "Secrets에 API 키가 없습니다. 아래에 임시로 입력할 수 있지만, "
                "이 방식은 새로고침/재배포 시 사라집니다.\n\n"
                "**영구 고정하려면** Streamlit Cloud 대시보드 → 이 앱 → Settings → Secrets에 "
                "DART_API_KEY, OPENAI_API_KEY를 등록하세요."
            )
            dart_key = dart_key or st.text_input("OpenDART API Key", type="password", key="dart_key_input")
            openai_key = openai_key or st.text_input("OpenAI API Key", type="password", key="openai_key_input")

        st.divider()
        st.subheader("가치평가 가정치 (조정 가능)")
        risk_free_rate = st.slider("무위험이자율 (국고채 10년, %)", 1.0, 6.0, 3.5, 0.1) / 100
        erp = st.slider("주식위험프리미엄(ERP, %)", 3.0, 8.0, 5.5, 0.1) / 100
        tax_rate = st.slider("법인세 실효세율 가정 (%)", 10.0, 30.0, 22.0, 0.5) / 100

    return dart_key, openai_key, risk_free_rate, erp, tax_rate


st.title("📊 AI 기업가치 평가 에이전트 (v1)")
st.caption(
    "OpenDART 공시 데이터 + KRX 시장데이터를 자동 수집해 ROIC · WACC · PBR 등 핵심 지표를 계산하고, "
    "AI가 산업별 숨은 신호 · 회계 이상징후 · 매수/매도 조건을 종합 해석합니다."
)
st.info("⚠️ 본 도구는 투자 참고용 정보 제공 서비스이며, 투자 자문이나 매수/매도 추천이 아닙니다. 최종 투자 판단과 책임은 본인에게 있습니다.", icon="⚠️")

dart_key, openai_key, risk_free_rate, erp, tax_rate = get_api_keys()

if not dart_key:
    st.stop()

# ------------------------------------------------------------------
# 기업 고유번호 매핑 (하루 1회 캐시)
# ------------------------------------------------------------------
@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_corp_map(_dart_key: str) -> pd.DataFrame:
    return dart_client.fetch_corp_code_df(_dart_key)


with st.spinner("기업 목록 불러오는 중... (최초 1회, 캐시됨)"):
    try:
        corp_df = load_corp_map(dart_key)
    except Exception as e:
        st.error(f"OpenDART 기업 목록 조회 실패: {e}\n\nOpenDART API 키를 확인해주세요.")
        st.stop()

# ------------------------------------------------------------------
# 기업 검색
# ------------------------------------------------------------------
company_name = st.text_input("🔎 분석할 기업명을 입력하세요 (예: 삼성전자)", "")

if not company_name:
    st.stop()

candidates = dart_client.search_company(corp_df, company_name, listed_only=True)

if candidates.empty:
    st.error("상장사 중 일치하는 기업을 찾지 못했습니다. 정확한 회사명을 입력해보세요 (예: '삼성전자', '카카오').")
    st.stop()

if len(candidates) > 1:
    options = candidates.apply(lambda r: f"{r['corp_name']} ({r['stock_code']})", axis=1).tolist()
    picked = st.selectbox("여러 후보가 검색되었습니다. 선택하세요:", options)
    row = candidates.iloc[options.index(picked)]
else:
    row = candidates.iloc[0]
    st.write(f"**대상 기업**: {row['corp_name']} ({row['stock_code']})")

corp_code = row["corp_code"]
stock_code = row["stock_code"]
corp_name = row["corp_name"]

run = st.button("🚀 분석 시작", type="primary")
if not run:
    st.stop()

# ------------------------------------------------------------------
# 재무제표 수집 (당기 기준 최신 사업보고서, 없으면 이전 연도로 fallback)
# ------------------------------------------------------------------
current_year = datetime.now().year
fin_df, fs_div_used, used_year = pd.DataFrame(), None, None

with st.spinner("OpenDART에서 재무제표 조회 중..."):
    for y in [current_year - 1, current_year - 2, current_year - 3]:
        df, fs_div = dart_client.get_financials_with_fallback(dart_key, corp_code, str(y))
        if not df.empty:
            fin_df, fs_div_used, used_year = df, fs_div, y
            break

if fin_df.empty:
    st.error("해당 기업의 사업보고서 재무제표를 찾지 못했습니다. (최근 상장/비적정 공시 등의 사유일 수 있습니다)")
    st.stop()

fs_label = "연결재무제표(CFS)" if fs_div_used == "CFS" else "별도재무제표(OFS, 연결 미공시로 대체)"
st.success(f"✅ {used_year}년 사업보고서 기준 {fs_label} 조회 완료")

three_year_items = financial_metrics.extract_three_year_items(fin_df)
items_t = three_year_items["thstrm"]
ratios = financial_metrics.compute_financial_ratios(items_t)
nopat, roic = financial_metrics.compute_roic(items_t, tax_rate=tax_rate)

# ------------------------------------------------------------------
# 시장 데이터 (KRX)
# ------------------------------------------------------------------
market_snapshot, beta = {}, None
if stock_code:
    with st.spinner("KRX 시장 데이터(주가/시가총액/PER/PBR/베타) 조회 중..."):
        try:
            market_snapshot = market_data.get_market_snapshot(stock_code)
            beta = market_data.estimate_beta(stock_code)
        except Exception as e:
            st.warning(f"시장 데이터 조회 중 일부 실패: {e}")

beta_used = beta if beta is not None else 1.0
wacc_result = None
if market_snapshot.get("market_cap"):
    wacc_result = financial_metrics.compute_wacc(
        market_cap=market_snapshot["market_cap"],
        interest_bearing_debt=items_t.get("interest_bearing_debt"),
        interest_expense=items_t.get("interest_expense"),
        risk_free_rate=risk_free_rate,
        beta=beta_used,
        equity_risk_premium=erp,
        tax_rate=tax_rate,
    )

# PBR/PER 자체 계산 (시장데이터 PBR/PER과 교차검증용)
pbr_calc = financial_metrics.safe_div(market_snapshot.get("market_cap"), items_t.get("total_equity"))
per_calc = financial_metrics.safe_div(market_snapshot.get("market_cap"), items_t.get("net_income"))

# ------------------------------------------------------------------
# 회계 이상징후 점검
# ------------------------------------------------------------------
flags = accounting_flags.check_flags(three_year_items)

# ------------------------------------------------------------------
# 화면 구성
# ------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(["📋 개요 & 시장데이터", "🧮 재무비율 · ROIC/WACC", "🚩 회계 이상징후", "🤖 AI 종합분석"])

with tab1:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("현재가", f"{market_snapshot.get('close_price', '-'):,}원" if market_snapshot.get("close_price") else "-")
    col2.metric("시가총액", f"{market_snapshot.get('market_cap', 0)/1e8:,.0f}억원" if market_snapshot.get("market_cap") else "-")
    col3.metric("PBR (시장)", f"{market_snapshot.get('pbr_market'):.2f}" if market_snapshot.get("pbr_market") else "-")
    col4.metric("PER (시장)", f"{market_snapshot.get('per_market'):.2f}" if market_snapshot.get("per_market") else "-")
    pbr_calc_str = f"{pbr_calc:.2f}" if pbr_calc else "-"
    st.caption(f"기준일: {market_snapshot.get('as_of', '-')} · 자체계산 PBR(시가총액/자본총계): {pbr_calc_str}")

    st.subheader("3개년 핵심 계정 (단위: 원)")
    df_show = pd.DataFrame(three_year_items).T
    df_show.index = ["당기", "전기", "전전기"]
    st.dataframe(df_show.style.format(lambda x: f"{x:,.0f}" if isinstance(x, (int, float)) and x is not None else "-"))

with tab2:
    c1, c2, c3 = st.columns(3)
    c1.metric("영업이익률", f"{ratios['operating_margin']:.1%}" if ratios["operating_margin"] is not None else "-")
    c1.metric("순이익률", f"{ratios['net_margin']:.1%}" if ratios["net_margin"] is not None else "-")
    c2.metric("ROE", f"{ratios['roe']:.1%}" if ratios["roe"] is not None else "-")
    c2.metric("ROA", f"{ratios['roa']:.1%}" if ratios["roa"] is not None else "-")
    c3.metric("부채비율", f"{ratios['debt_ratio']:.1%}" if ratios["debt_ratio"] is not None else "-")
    c3.metric("유동비율", f"{ratios['current_ratio']:.1%}" if ratios["current_ratio"] is not None else "-")

    st.divider()
    st.subheader("ROIC vs WACC (경제적 부가가치 창출 여부)")
    c1, c2, c3 = st.columns(3)
    c1.metric("ROIC", f"{roic:.1%}" if roic is not None else "데이터 부족")
    if wacc_result:
        c2.metric("WACC", f"{wacc_result['wacc']:.1%}")
        spread = (roic - wacc_result["wacc"]) if roic is not None else None
        c3.metric("스프레드 (ROIC-WACC)", f"{spread:+.1%}" if spread is not None else "-",
                  delta=None if spread is None else ("가치창출" if spread > 0 else "가치파괴"))
        with st.expander("WACC 산출 상세"):
            st.json({k: (f"{v:.2%}" if isinstance(v, float) and k != "weight_equity" and k != "weight_debt" else v) for k, v in wacc_result.items()})
            st.caption(f"사용된 베타(β): {beta_used:.2f}" + (" (추정 실패로 기본값 1.0 사용)" if beta is None else " (최근 3년 KOSPI 대비 회귀추정)"))
    else:
        c2.metric("WACC", "계산 불가 (시장데이터 부족)")

with tab3:
    st.subheader("규칙 기반 회계 이상징후 점검 결과")
    for f in flags:
        color = {"정상": "green", "주의": "orange", "경고": "red"}.get(f["level"], "gray")
        st.markdown(f"**:{color}[[{f['level']}] {f['title']}]**")
        st.write(f["detail"])
        st.write("")
    st.caption("※ 이는 정량 규칙 기반의 참고 신호이며, 회계 부정/오류를 확정하는 판단이 아닙니다.")

with tab4:
    st.subheader("AI 종합 분석 리포트")
    st.caption("가치평가 / 산업별 숨은 신호 / 회계 이상징후 해석 / 매수·매도 조건을 한 번에 생성합니다. (OpenAI API 호출 1회, 비용 발생)")

    if st.button("🤖 AI 분석 실행", type="primary"):
        if not openai_key:
            st.error("OpenAI API 키가 설정되지 않았습니다. 사이드바에서 입력하거나 Secrets에 등록해주세요.")
        else:
            payload = {
                "company": corp_name,
                "stock_code": stock_code,
                "fiscal_year": used_year,
                "fs_type": fs_label,
                "three_year_raw_items": three_year_items,
                "financial_ratios": ratios,
                "roic": roic,
                "wacc_analysis": wacc_result,
                "beta_used": beta_used,
                "market_snapshot": market_snapshot,
                "pbr_self_calculated": pbr_calc,
                "per_self_calculated": per_calc,
                "assumptions": {
                    "risk_free_rate": risk_free_rate,
                    "equity_risk_premium": erp,
                    "tax_rate": tax_rate,
                },
                "accounting_flags": flags,
            }
            with st.spinner("AI가 데이터를 종합 분석하는 중..."):
                try:
                    report = ai_agent.run_analysis(openai_key, payload)
                    st.markdown(report)
                except Exception as e:
                    st.error(f"AI 분석 실패: {e}")

st.divider()
st.caption("Data source: OpenDART(전자공시시스템), KRX(pykrx) · 본 서비스는 투자 자문이 아닌 정보 제공 목적입니다.")

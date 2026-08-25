# -*- coding: utf-8 -*-
"""
OpenDART(전자공시시스템 Open API) 연동 모듈
- 기업 고유번호(corp_code) 매핑 다운로드/파싱
- 회사명으로 기업 검색
- 단일회사 전체 재무제표 조회
"""
import io
import zipfile
import xml.etree.ElementTree as ET

import requests
import pandas as pd

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
FIN_STATEMENT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
COMPANY_INFO_URL = "https://opendart.fss.or.kr/api/company.json"

# 사업보고서(연간) 기준. 최신 분기를 보고 싶으면 11013(1분기)/11012(반기)/11014(3분기)로 변경 가능
REPRT_CODE_ANNUAL = "11011"


def fetch_corp_code_df(api_key: str) -> pd.DataFrame:
    """OpenDART에서 전체 기업 고유번호 목록을 받아 DataFrame으로 반환.
    컬럼: corp_code, corp_name, stock_code, modify_date
    상장사만 쓸 경우 stock_code가 빈 문자열이 아닌 행만 필터링해서 사용하면 됨.
    """
    resp = requests.get(CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=30)
    resp.raise_for_status()

    # 정상 응답은 zip 바이너리. 에러(키 오류 등)일 경우 JSON 텍스트가 옴.
    content_type = resp.headers.get("Content-Type", "")
    if "json" in content_type or resp.content[:1] in (b"{", b"["):
        raise RuntimeError(f"OpenDART 응답 오류: {resp.text}")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read("CORPCODE.xml")

    root = ET.fromstring(xml_bytes)
    rows = []
    for item in root.findall("list"):
        rows.append(
            {
                "corp_code": (item.findtext("corp_code") or "").strip(),
                "corp_name": (item.findtext("corp_name") or "").strip(),
                "stock_code": (item.findtext("stock_code") or "").strip(),
                "modify_date": (item.findtext("modify_date") or "").strip(),
            }
        )
    return pd.DataFrame(rows)


def search_company(corp_df: pd.DataFrame, name: str, listed_only: bool = True) -> pd.DataFrame:
    """회사명(부분일치)으로 후보를 검색. 기본적으로 상장사(stock_code 존재)만 반환."""
    name = name.strip()
    df = corp_df[corp_df["corp_name"].str.contains(name, case=False, na=False)]
    if listed_only:
        df = df[df["stock_code"].str.len() > 0]
    # 정확히 일치하는 이름을 우선 정렬
    df = df.copy()
    df["exact"] = df["corp_name"] == name
    df = df.sort_values(["exact", "corp_name"], ascending=[False, True]).drop(columns="exact")
    return df.reset_index(drop=True)


def get_financial_statements(
    api_key: str,
    corp_code: str,
    bsns_year: str,
    reprt_code: str = REPRT_CODE_ANNUAL,
    fs_div: str = "CFS",
) -> pd.DataFrame:
    """단일회사 전체 재무제표(fnlttSinglAcntAll) 조회.
    fs_div: 'CFS'(연결) 또는 'OFS'(별도)
    실패/데이터없음이면 빈 DataFrame 반환.
    """
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    resp = requests.get(FIN_STATEMENT_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "000":
        # 013: 조회된 데이터 없음 등 -> 빈 DF로 처리 (연결 없으면 별도로 재시도하는 로직은 상위에서 처리)
        return pd.DataFrame()

    df = pd.DataFrame(data["list"])
    for col in ["thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .replace({"": None, "nan": None})
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_financials_with_fallback(api_key: str, corp_code: str, bsns_year: str, reprt_code: str = REPRT_CODE_ANNUAL):
    """연결재무제표(CFS)를 우선 조회하고, 없으면 별도재무제표(OFS)로 자동 대체.
    반환: (DataFrame, 사용된 fs_div)
    """
    df = get_financial_statements(api_key, corp_code, bsns_year, reprt_code, fs_div="CFS")
    if not df.empty:
        return df, "CFS"
    df = get_financial_statements(api_key, corp_code, bsns_year, reprt_code, fs_div="OFS")
    return df, "OFS"


def get_company_overview(api_key: str, corp_code: str) -> dict:
    """기업 개황 정보(업종, 대표자, 상장일 등)."""
    resp = requests.get(COMPANY_INFO_URL, params={"crtfc_key": api_key, "corp_code": corp_code}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "000":
        return {}
    return data

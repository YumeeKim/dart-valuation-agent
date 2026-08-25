# -*- coding: utf-8 -*-
"""
OpenAI API를 호출해 정량 데이터(재무비율, ROIC/WACC, 회계 이상징후 등)를
종합적으로 해석하는 AI 에이전트 모듈.

MODEL_NAME은 OpenAI 모델 라인업이 바뀌면 이 상수만 수정하면 됩니다.
(2026년 기준 모델명은 https://platform.openai.com/docs/models 에서 최신 확인 권장)
"""
import json
from openai import OpenAI

MODEL_NAME = "gpt-4o"

SYSTEM_PROMPT = """당신은 20년 경력의 한국 주식시장 전문 밸류에이션 애널리스트입니다.
사용자가 제공하는 정량 데이터(OpenDART 재무제표 기반 재무비율, ROIC, WACC, 시장 데이터,
규칙 기반 회계 이상징후 점검 결과)를 바탕으로 아래 4가지 항목을 반드시 포함해
전문적이면서도 이해하기 쉬운 한국어 리포트를 작성하세요.

1. 종합 가치평가 (ROIC vs WACC 스프레드로 본 경제적 부가가치 창출 여부, PBR/PER의 상대적 수준,
   저평가/고평가 여부에 대한 균형잡힌 의견)
2. 산업별 숨은 신호 (해당 기업이 속한 산업의 특성상 겉으로 드러난 숫자 이면에서 살펴봐야 할 요소.
   예: 반도체는 재고평가손실/가동률, 건설은 미청구공사, 금융은 충당금 적립 수준, 바이오는 임상 파이프라인 등.
   업종을 알 수 없으면 그 사실을 명시하고 일반적인 체크포인트를 제시)
3. 회계 이상징후 해석 (제공된 규칙 기반 점검 결과를 업종/사업 맥락과 함께 재해석. 과잉해석 경계)
4. 매수/매도 판단 조건 (특정 매수·매도를 지금 추천하는 것이 아니라, "이런 조건이 충족/악화되면
   매수 관점/매도 관점을 고려해볼 수 있다"는 형태의 조건부 체크리스트로 제시)

반드시 지킬 것:
- 투자 자문이 아니라 정보 제공 목적임을 리포트 서두 또는 말미에 1회 명시
- 데이터가 없거나(None) 추정치인 항목은 반드시 "데이터 없음/추정치"라고 밝히고, 이를 근거로 과도한 확신을 갖지 말 것
- 근거 없는 목표주가나 100% 확신 표현 금지, 대신 조건부/확률적 표현 사용
- 마크다운 헤더(##)로 4개 섹션을 명확히 구분
"""


def build_user_prompt(payload: dict) -> str:
    return (
        "다음은 한 기업에 대해 자동 수집/계산된 데이터입니다. JSON 형식이며, "
        "값이 null이면 해당 데이터를 확보하지 못했다는 뜻입니다.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
        "위 데이터를 바탕으로 지시된 4개 섹션 리포트를 작성해주세요."
    )


def run_analysis(api_key: str, payload: dict) -> str:
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(payload)},
        ],
        temperature=0.4,
        max_tokens=3000,
    )
    return resp.choices[0].message.content

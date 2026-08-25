# 📊 AI 기업가치 평가 에이전트 (v1)

기업명을 입력하면 OpenDART 공시 데이터 + KRX 시장데이터를 자동 수집해
**ROIC · WACC · PBR · PER · ROE** 등 핵심 지표를 계산하고, AI가
**가치평가 / 산업별 숨은 신호 / 회계 이상징후 / 매수·매도 조건**을 종합 리포트로 작성해줍니다.

> ⚠️ 투자 자문이 아닌 정보 제공 목적의 개인용 v1 도구입니다.

---

## 1. 아키텍처

```
사용자(크롬 브라우저)
   │  기업명 입력
   ▼
Streamlit 웹앱 (Streamlit Community Cloud에 배포)
   │
   ├─ OpenDART API   → 기업 고유번호 조회, 3개년 재무제표 수집
   ├─ pykrx (KRX)    → 현재가, 시가총액, PER/PBR, 베타 계산용 시세
   ├─ 자체 계산 로직  → ROIC, WACC, 재무비율, 회계 이상징후 룰체크
   └─ OpenAI API     → 위 결과를 종합해 4대 항목 리포트 생성
```

## 2. 폴더 구조

```
dart-valuation-agent/
├── app.py                          # Streamlit 메인 앱
├── requirements.txt
├── .gitignore
├── .streamlit/
│   └── secrets.toml.example        # 실제 secrets.toml은 절대 GitHub에 올리지 마세요
└── modules/
    ├── dart_client.py              # OpenDART 연동 (기업검색, 재무제표)
    ├── market_data.py              # KRX 시세/시가총액/베타 (pykrx)
    ├── financial_metrics.py        # ROIC/WACC/재무비율 계산
    ├── accounting_flags.py         # 회계 이상징후 룰체크
    └── ai_agent.py                 # OpenAI 종합분석 프롬프트/호출
```

## 3. API 키 발급

1. **OpenDART API 키** (무료): https://opendart.fss.or.kr → 회원가입 → 인증키 신청 → 이메일로 키 수령
2. **OpenAI API 키**: https://platform.openai.com/api-keys → 결제수단 등록 후 키 생성

## 4. 배포 순서 (요청하신 루트 그대로)

### Step 1. GitHub에 코드 올리기
```bash
cd dart-valuation-agent
git init
git add .
git commit -m "v1: DART 기반 AI 가치평가 에이전트"
git branch -M main
git remote add origin https://github.com/{본인아이디}/dart-valuation-agent.git
git push -u origin main
```
※ `.streamlit/secrets.toml`(실제 키가 담긴 파일)은 `.gitignore`에 이미 포함되어 있어 실수로 올라가지 않습니다.

### Step 2. Streamlit Community Cloud 배포
1. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
2. "New app" 클릭 → 방금 올린 저장소(repo) 선택
3. Main file path: `app.py` 입력 후 Deploy 클릭

### Step 3. API 키를 "한 번만" 고정 등록 (핵심)
배포된 앱 화면 우측 하단(또는 대시보드) → **Settings → Secrets** 로 이동해서 아래 내용을 붙여넣기:
```toml
DART_API_KEY = "발급받은_OpenDART_키"
OPENAI_API_KEY = "발급받은_OpenAI_키"
```
저장하면 앱이 자동 재시작되며, **이후로는 누가 접속해도 키를 다시 입력할 필요 없이 고정**됩니다.
(앱 코드는 `st.secrets`를 우선적으로 읽도록 이미 구현되어 있습니다.)

### Step 4. 웹주소 생성 & 사용
배포가 끝나면 `https://{본인앱이름}.streamlit.app` 형태의 고유 URL이 생성됩니다.
이 주소를 크롬에서 열고 → 기업명 입력 → "분석 시작" → "AI 분석 실행" 버튼을 누르면 끝입니다.

## 5. v1의 한계 (정직하게 밝힙니다)

- **계정과목 자동 매칭의 한계**: DART 재무제표는 IFRS 표준 계정ID가 어느 정도 통일돼 있지만
  회사마다 세부 표기가 다를 수 있어, 일부 항목(특히 차입금·이자비용)은 이름 기반 추정치입니다.
  값이 비어있으면 "데이터 없음"으로 표시되고 AI 프롬프트에도 그대로 전달됩니다.
- **WACC의 베타/무위험이자율/ERP**는 사이드바에서 조정 가능한 가정치이며, 정답이 아닙니다.
- **회계 이상징후 점검은 규칙 기반(threshold rule)**으로, 실제 회계부정 여부를 판정하지 않습니다.
- 최신 분기(11013/11012/11014) 대신 **연간 사업보고서(11011)** 기준입니다. 최신 분기로 바꾸려면
  `app.py`의 연도/보고서코드 루프 부분만 수정하면 됩니다.
- pykrx는 상장사(코스피/코스닥)만 지원합니다. 비상장사는 시장데이터(WACC, PBR/PER)가 나오지 않습니다.

## 6. 다음 버전(v2) 아이디어
- 계정과목 매칭 정확도 개선 (XBRL 원본 태그 직접 파싱)
- 최신 분기 실적 자동 반영 + 여러 연도 추이 차트
- 동일 업종 Peer 그룹과의 상대 밸류에이션 비교
- 대화형 AI 에이전트(후속 질문 가능한 챗 형태)로 확장

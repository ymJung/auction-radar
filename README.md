# ⚖️ AuctionRadar (경매 매력매물 발굴 · 낙찰가 추적 · 입찰가 추천 서버)

> **프로젝트 아키텍처 및 유지보수 가이드**
> 본 문서는 향후 기능 수정이나 조건 변경 시 즉시 컨텍스트를 파악하고 반영할 수 있도록 작성되었습니다.

---

## 1. 프로젝트 핵심 요구사항 및 비즈니스 로직 요약

### A. 매력적인 경매 매물 4대 필터링 조건
법원경매 원천 데이터(현황조사서, 매각물건명세서, 사건내역)를 파싱하여 아래 조건을 **모두 만족**하는 물건만 `is_attractive = True`로 분류합니다:
1. **임차인 없음 (`has_tenant == False`)**: 전입세대 및 현황조사서상 대항력/보증금 인수 리스크가 없는 물건
2. **소유자 거주 중 (`occupant_type == "소유자"`)**: 채무자(소유자) 및 그 가족이 직접 점유·거주하여 명도가 깔끔한 물건
3. **권리상 하자 없음 (`has_rights_defect == False` & `assumed_rights_amount == 0`)**: 말소기준권리 이후 모든 등기 권리가 소멸하고, 유치권·법정지상권·선순위 가처분/가등기·위반건축물 등 매수인 인수 사항이 없는 물건
4. **미납 관리비 검증 및 공용부분 선제 차감 (`unpaid_mgmt_fee`)**:
   - 과도한 장기 체납(기본 한도 `1,000만원` 초과) 물건은 필터에서 제외
   - 허용 범위 내 미납 관리비가 있는 경우, 대법원 판례상 낙찰자가 인수하는 **공용관리비 비중(기본 `75%`, `COMMON_MGMT_FEE_ASSUMPTION_RATIO = 0.75`)**을 산출하여 **추천 입찰가 및 순안전마진에서 선제 차감**

### B. 교차 분석하는 6대 부동산 데이터 소스
추려진 경매 매물의 정확한 시세와 출구 전략(매매/전세 레버리지)을 판단하기 위해 아래 6개 사이트 데이터를 결합합니다:
- **① 디스코 (`DiscoScraper`)**: 지도에서 인근 실제 팔린 가격(매각/실거래 평균가 및 평당가)
- **② 국토부 실거래 (`MolitScraper`)**: 해당 법정동 동네 거래 내역을 통째로 수집하여 유사 전용면적(±15㎡) 평균·최저·최고 실거래가 산출
- **③ 아실 (`AsilScraper`)**: 재개발·재건축 정비구역도(신속통합기획, 모아타운 등) 포함 여부 + 경매물건 분석
- **④ 부동산플래닛 (`BdsPlanetScraper`)**: 건물 사용승인일/준공연도 파싱 → **건물이 몇 년 됐는지(`building_age_years`)** 및 노후도 등급 산출
- **⑤ 공시가격알리미 (`OfficialPriceScraper`)**: 공시가격 조회 및 **전세보증보험 가입 한도(`공시가 × 126%`, 10월 기준)** 자동 계산
  - *핵심 지표*: 추천 입찰가가 `공시가 × 126%` 이하이면 낙찰 후 보증보험 전세 세팅을 통한 **무피/초소액 레버리지 투자 가능(`can_zero_gap_invest = True`)** 매물로 분류
- **⑥ 네이버부동산 (`NaverLandScraper`)**: 현재 시장에 나와 있는 매매 최저호가·평균호가·전세 평균호가

### C. 낙찰 결과 추적 및 3단계 입찰가 추천 로직
- **과거 낙찰 추적 DB (`winning_bid_history`)**: 유사 조건(소유자 거주, 무하자, 건물 연식, 재개발 구역 여부, 물건종류) 매물이 실제로 얼마에 낙찰되었는지(감정가 대비 낙찰가율, 실거래 시세 대비 낙찰가율, 응찰자 수) 추적
- **입찰가 산정 공식 (`app/analyzer.py`)**:
  1. `기준 시세(estimated_market_value)` = 국토부 동네 실거래 평균(40%) + 디스코 인근 실매각가(30%) + 네이버 최저호가×0.96(30%)
  2. `목표 시세대비 낙찰가율` = 유사 물건 과거 평균 시세대비 낙찰가율 + 아실 재개발 구역 프리미엄(`+2.5%p`) + 부동산플래닛 건물 연식 보정(7년 이하 `+1.5%p`, 비재개발 20년 이상 `-2.0%p`)
  3. `적정 추천 입찰가(optimal_bid)` = `(기준 시세 × 목표 시세대비 낙찰가율) - 인수 예상 공용 미납관리비`
  4. **3단계 추천가 제공**:
     - 보수적 입찰가 (예상 낙찰확률 ~42%)
     - **⭐ 적정 추천 입찰가 (예상 낙찰확률 ~74%)**
     - 공격형 입찰가 (예상 낙찰확률 ~89%)

---

## 2. 디렉토리 및 파일 구조 (수정 시 참고할 위치)

```text
auction-radar/
├── .env.example               # 환경변수 설정 예시 파일 (~/.env 또는 프로젝트 .env에 설정)
├── app/
│   ├── config.py              # 환경변수(~/.env, .env) 로드, 126% 보증보험 배수, 미납관리비 인수비율(75%) 등 핵심 상수
│   ├── models.py              # Pydantic 데이터 스키마 (AuctionProperty, 6대 사이트 모델, BidRecommendation, WinningBidRecord)
│   ├── analyzer.py            # 매력 매물 필터링 판정, 3단계 입찰가 추천 계산, 실시간 입찰 시뮬레이터 로직
│   ├── database.py            # SQLite(data/auction_radar.db) 저장/조회 및 신규 낙찰 결과 등록 시 전체 추천가 재계산
│   ├── telegram_notifier.py   # 텔레그램 봇 연동, 인라인/하단 고정 앱 버튼 생성 및 Long-Polling 워커
│   ├── weekly_job.py          # 주 1회(또는 수동) 재스크래핑 + DB 갱신 + 텔레그램 발송 배치 스크립트
│   ├── main.py                # FastAPI 서버, 웹 대시보드 라우터, REST API, 내장 APScheduler 주간 크론잡
│   ├── scrapers/
│   │   ├── parsers.py         # 법원경매(현황조사서/매각물건명세서) 및 6대 부동산 사이트 HTML/XML/JSON 파서
│   │   └── pipeline.py        # 전체 수집·파싱 파이프라인 및 낙찰 추적 데이터 구성
│   └── templates/
│       └── index.html         # Tailwind CSS 기반 반응형 웹 대시보드 UI (필터 탭, 시뮬레이터, 낙찰 기록 폼)
├── scripts/
│   └── keepalive.sh           # 세션 종료/재부팅 후에도 서버(포트 8080) 및 텔레그램 버튼 워커를 무중단 유지하는 데몬 스크립트
├── tests/
│   └── test_pipeline_and_api.py # 파서, 126% 룰, 필터링, API 엔드포인트 검증 pytest 스위트
├── data/
│   └── auction_radar.db       # SQLite 데이터베이스 (자동 생성 및 시드, .gitignore 제외)
└── logs/                      # 실행 로그 및 PID 파일 (.gitignore 제외)
```

---

## 3. 향후 수정사항 발생 시 빠른 가이드 (How to Modify)

1. **필터링 기준이나 전세보증보험 한도율(126%)·미납관리비 기준을 바꾸고 싶을 때**
   - `app/config.py`: `JEONSE_INSURANCE_RATIO` (`1.26`), `COMMON_MGMT_FEE_ASSUMPTION_RATIO` (`0.75`), `MAX_ACCEPTABLE_UNPAID_MGMT_FEE` (`10_000_000`) 수정
   - `app/analyzer.py`: `evaluate_and_recommend()` 내 필터 조건 또는 가중치 수정
2. **입찰가 추천 공식이나 낙찰 확률 시뮬레이션 곡선을 조정하고 싶을 때**
   - `app/analyzer.py`의 `evaluate_and_recommend()` 및 `simulate_bid_for_property()` 수정
3. **스크래핑/파싱 로직 또는 대상 매물을 추가·변경하고 싶을 때**
   - 파서 정규식/태그 수정: `app/scrapers/parsers.py`
   - 수집 파이프라인 수정: `app/scrapers/pipeline.py`
4. **텔레그램 메시지 포맷이나 앱 버튼(인라인 버튼 / 하단 키보드) 구성을 바꾸고 싶을 때**
   - `~/.env` (또는 프로젝트 루트 `.env`) 파일의 `TELEGRAM_BOT_2` 및 `TELEGRAM_USER_ID` 환경변수를 사용합니다. (`.env.example` 참고)
   - 버튼 레이아웃 및 클릭 시 응답 로직은 `app/telegram_notifier.py`의 `build_main_menu_keyboard()`, `build_persistent_reply_keyboard()`, `TelegramBotPoller.route_callback()`, `TelegramBotPoller.route_message_text()`에서 수정합니다.
5. **웹 대시보드 화면(UI)을 수정하고 싶을 때**
   - `app/templates/index.html` 수정

---

## 4. 백그라운드 무중단 운영 및 크론잡 관리

이 프로젝트는 세션이 닫히거나 서버가 재부팅되어도 계속 동작하도록 **OS `crontab` + `setsid` 독립 데몬**으로 운영할 수 있습니다.

### Linux `crontab` 설정 예시 (`crontab -e`)
```cron
# 1. 재부팅 시 및 5분마다 서버(웹 대시보드 + 텔레그램 앱 버튼 폴러) 생존 확인 및 자동 복구
@reboot /path/to/auction-radar/scripts/keepalive.sh
*/5 * * * * /path/to/auction-radar/scripts/keepalive.sh

# 2. 매주 월요일 오전 09:00 6대 사이트 재스크래핑 및 텔레그램 리포트 자동 발송
0 9 * * 1 cd /path/to/auction-radar && ~/.local/bin/uv run python -m app.weekly_job >> /path/to/auction-radar/logs/weekly_cron.log 2>&1
```

### 코드 수정 후 서버 재시작 및 테스트 방법
```bash
# 기존 서버 종료 후 keepalive 스크립트로 즉시 재기동
pkill -f "[u]vicorn app.main:app" || true
./scripts/keepalive.sh

# 테스트 실행
uv run pytest -v
```

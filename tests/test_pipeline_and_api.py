from fastapi.testclient import TestClient
from app.main import app
from app.scrapers.parsers import (
    BdsPlanetScraper,
    CourtAuctionParser,
    MolitScraper,
    OfficialPriceScraper,
)
from app.scrapers.pipeline import run_scraping_and_analysis_pipeline


def test_court_auction_parser_clean_vs_defective():
    clean_html = """
    <div>
        현황조사서: 채무자(소유자) 점유, 임차인 없음. 소유자 직접 거주 중.
        매각물건명세서: 말소기준권리 이후 전부 소멸. 인수할 사항 없음.
        미납관리비 85만원 (5개월분 연체)
    </div>
    """
    res = CourtAuctionParser.parse_occupancy_and_rights(clean_html)
    assert res["has_tenant"] is False
    assert res["occupant_type"] == "소유자"
    assert res["has_rights_defect"] is False
    assert res["unpaid_mgmt_fee"] == 850_000
    assert res["unpaid_mgmt_months"] == 5

    defect_html = """
    <div>
        현황조사서: 주거임차인 박OO (보증금 20,000만원) 대항력 있는 임차인 존재.
        매각물건명세서: 보증금 전액 인수 조건.
        미납관리비 1,200만원 (24개월분 연체)
    </div>
    """
    res2 = CourtAuctionParser.parse_occupancy_and_rights(defect_html)
    assert res2["has_tenant"] is True
    assert res2["occupant_type"] == "임차인"
    assert res2["has_rights_defect"] is True
    assert res2["unpaid_mgmt_fee"] == 12_000_000


def test_official_price_126_percent_rule():
    # ⑤ 공시가격알리미: 공시가 2억 6,500만원 × 126% = 3억 3,390만원
    data = OfficialPriceScraper.calculate_insurance_limit(
        official_price=265_000_000,
        reference_bid_price=318_000_000,
    )
    assert data.jeonse_insurance_limit == 333_900_000
    assert data.can_zero_gap_invest is True


def test_bdsplanet_building_age():
    # ④ 부동산플래닛: 건물이 몇 년 됐는지 (2018년 준공 -> 2026년 기준 8년차)
    bds = BdsPlanetScraper.compute_building_age("2018-05-14", total_floors=5, reference_year=2026)
    assert bds.built_year == 2018
    assert bds.building_age_years == 8


def test_pipeline_and_api_endpoints():
    props, history = run_scraping_and_analysis_pipeline()
    attractive = [p for p in props if p.is_attractive]
    rejected = [p for p in props if not p.is_attractive]

    assert len(attractive) >= 5
    assert len(rejected) == 2
    assert len(history) >= 8

    for p in attractive:
        assert p.has_tenant is False
        assert p.occupant_type == "소유자"
        assert p.has_rights_defect is False
        assert p.recommendation is not None
        assert p.recommendation.optimal_bid > p.min_bid_price

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AuctionRadar" in resp.text

    sim_resp = client.post(
        "/api/simulate-bid",
        json={"case_no": "2026타경104821", "bid_amount": 800_000_000},
    )
    assert sim_resp.status_code == 200
    sim_data = sim_resp.json()
    assert "estimated_win_probability" in sim_data
    assert "expected_net_profit" in sim_data

    # 과거 낙찰 데이터 기준: 제시 낙찰가, 낙찰 시 이득, 2등과의 차이 시뮬레이션 검증
    for h in history:
        assert h.suggested_optimal_bid > h.min_bid_price
        assert h.second_bid_price > 0
        assert h.winning_bid_price > h.second_bid_price
        assert h.gap_1st_to_2nd_price == h.winning_bid_price - h.second_bid_price
        assert h.gap_suggested_to_2nd == h.suggested_optimal_bid - h.second_bid_price
        assert h.suggested_optimal_net_profit != 0
        assert h.actual_winner_net_profit != 0
        assert len(h.simulation_verdict) > 10

    hist_sim_resp = client.post(
        "/api/history/simulate",
        json={"case_no": "2025타경101204", "bid_amount": 528_000_000},
    )
    assert hist_sim_resp.status_code == 200
    hsim_data = hist_sim_resp.json()
    assert hsim_data["case_no"] == "2025타경101204"
    assert hsim_data["simulated_rank"] == 2  # 2등(5.18억)은 제쳤으나 1등(5.315억)보다는 낮음
    assert hsim_data["gap_vs_2nd"] == 10_000_000
    assert hsim_data["gap_vs_1st"] == -3_500_000
    assert hsim_data["simulated_net_profit"] > 0

    # 생성형 AI(제미나이 등) 토론용 매물 상세 텍스트 추출 및 자금 유동성 전략 선택 API 검증
    strat_catalog_resp = client.get("/api/funding-strategies")
    assert strat_catalog_resp.status_code == 200
    strat_catalog = strat_catalog_resp.json()
    assert strat_catalog["ok"] is True
    assert "newborn_special" in strat_catalog["default_strategies"]
    assert "first_time_buyer" in strat_catalog["default_strategies"]

    ai_resp = client.get(
        "/api/properties/2026타경104821/ai-text?include_prompt=true&strategies=newborn_special,first_time_buyer,auction_balance_loan&available_cash=250000000"
    )
    assert ai_resp.status_code == 200
    ai_data = ai_resp.json()
    assert ai_data["ok"] is True
    assert ai_data["case_no"] == "2026타경104821"
    assert ai_data["selected_strategies"] == ["newborn_special", "first_time_buyer", "auction_balance_loan"]
    assert ai_data["available_cash"] == 250000000
    assert "6대 부동산 플랫폼 교차 분석 데이터" in ai_data["text"]
    assert "자금 유동성 확인 및 가용 대출·레버리지 전략 분석" in ai_data["text"]
    assert "신생아 특례 디딤돌 대출" in ai_data["text"]
    assert "생애최초 주택구입 대출" in ai_data["text"]
    assert "경매 경락잔금대출" in ai_data["text"]
    assert "생성형 AI(Gemini 등)와 토론하고 싶은 핵심 질문" in ai_data["text"]

    ai_raw_resp = client.get("/api/properties/2026타경104821/ai-text?include_prompt=false&strategies=none")
    assert ai_raw_resp.status_code == 200
    assert "생성형 AI(Gemini 등)와 토론하고 싶은 핵심 질문" not in ai_raw_resp.json()["text"]
    assert "자금 유동성 확인 및 가용 대출·레버리지 전략 분석" not in ai_raw_resp.json()["text"]

    bulk_ai_resp = client.get("/api/properties-ai-text?attractive_only=true&include_prompt=true&strategies=all")
    assert bulk_ai_resp.status_code == 200
    bulk_data = bulk_ai_resp.json()
    assert bulk_data["ok"] is True
    assert bulk_data["count"] >= 5
    assert len(bulk_data["selected_strategies"]) == 6
    assert "추출 매물 핵심 요약 비교표" in bulk_data["text"]

    # 경매 사건번호 맞춤 정밀 분석 실행 API (/api/analyze-case) 검증
    case_resp = client.post(
        "/api/analyze-case",
        json={"case_no": "2025타경 2768", "send_telegram": False},
    )
    assert case_resp.status_code == 200
    case_data = case_resp.json()
    assert case_data["ok"] is True
    assert case_data["case_no"] == "2025타경2768"
    assert len(case_data["pipeline_steps"]) == 5
    assert case_data["property"]["recommendation"]["optimal_bid"] > 0
    assert "2025타경2768" in case_data["ai_discussion_text"]

    # 과거 낙찰 히스토리 사건번호 입력 시에도 전 과정 파이프라인이 정상 구동되는지 검증
    hist_case_resp = client.post(
        "/api/analyze-case",
        json={"case_no": "2025타경 101204", "send_telegram": False},
    )
    assert hist_case_resp.status_code == 200
    hist_case_data = hist_case_resp.json()
    assert hist_case_data["case_no"] == "2025타경101204"
    assert len(hist_case_data["pipeline_steps"]) == 5
    assert "상계동" in hist_case_data["property"]["address"]




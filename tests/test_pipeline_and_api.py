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

    assert len(attractive) == 5
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

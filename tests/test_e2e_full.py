from typing import Any, Dict, List
import httpx
from fastapi.testclient import TestClient

from app.config import settings
from app.database import (
    ensure_seeded,
    get_connection,
    load_all_properties,
    load_property_by_case_no,
    load_winning_history,
)
from app.main import app
from app.telegram_notifier import bot_poller

client = TestClient(app)
LIVE_BASE_URL = f"http://127.0.0.1:{settings.PORT}"


def test_e2e_1_mysql_database_and_seeding_verification() -> None:
    """E2E 1: Docker MySQL 8.0 (auction_radar DB) 연결, 테이블 스키마 및 초기 시드 데이터 검증"""
    ensure_seeded()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DATABASE() AS db_name")
            row = cur.fetchone()
            assert row is not None
            assert row["db_name"] == settings.MYSQL_DATABASE

            cur.execute("SHOW TABLES")
            tables = {list(r.values())[0] for r in cur.fetchall()}
            assert "auction_properties" in tables
            assert "winning_bid_history" in tables

    all_props = load_all_properties(attractive_only=False)
    attractive_props = load_all_properties(attractive_only=True)
    history = load_winning_history()

    assert len(all_props) >= 7
    assert len(attractive_props) == 5
    assert len(history) >= 8


def test_e2e_2_four_filter_rules_and_six_platforms_cross_analysis() -> None:
    """E2E 2: 매력 매물 4대 조건(임차인無·소유자거주·권리무하자·미납관리비검증) 및 6대 부동산 플랫폼 데이터 교차검증"""
    res_attr = client.get("/api/properties", params={"attractive_only": "true"})
    assert res_attr.status_code == 200
    attractive_list: List[Dict[str, Any]] = res_attr.json()
    assert len(attractive_list) == 5

    for prop in attractive_list:
        # 4대 핵심 필터 검증
        assert prop["is_attractive"] is True
        assert prop["has_tenant"] is False
        assert prop["occupant_type"] == "소유자"
        assert prop["has_rights_defect"] is False
        assert prop["assumed_rights_amount"] == 0
        assert prop["unpaid_mgmt_fee"] <= settings.MAX_ACCEPTABLE_UNPAID_MGMT_FEE

        # 6대 사이트 데이터 존재 검증 (①디스코, ②국토부실거래, ③아실, ④부동산플래닛, ⑤공시가격알리미 126%, ⑥네이버부동산)
        assert prop["disco"]["nearby_sold_price_avg"] > 0
        assert prop["molit"]["similar_area_avg_price"] > 0
        assert "is_redev_zone" in prop["asil"]
        assert prop["bdsplanet"]["building_age_years"] >= 0
        assert prop["official_price"]["jeonse_insurance_limit"] == int(
            round(prop["official_price"]["official_price"] * 1.26)
        )
        assert prop["naver_land"]["asking_sale_min"] > 0

        # 3단계 추천 입찰가 검증 (보수적 < 적정 < 공격형)
        rec = prop["recommendation"]
        assert rec is not None
        assert rec["conservative_bid"] < rec["optimal_bid"] < rec["aggressive_bid"]
        assert rec["assumed_unpaid_mgmt_fee"] == int(round((prop["unpaid_mgmt_fee"] * 0.75) / 10_000) * 10_000)


def test_e2e_3_custom_bid_simulation_and_winning_bid_recording_lifecycle() -> None:
    """E2E 3: 실시간 입찰가 시뮬레이션 -> 신규 낙찰 결과 등록(MySQL 저장 & 전체 추천가 재계산) -> 테스트 레코드 정리"""
    # 1. 입찰가 시뮬레이션 API 검증 (보수적 금액 vs 공격적 금액 비교)
    low_sim = client.post(
        "/api/simulate-bid",
        json={"case_no": "2026타경104821", "bid_amount": 720_000_000},
    )
    high_sim = client.post(
        "/api/simulate-bid",
        json={"case_no": "2026타경104821", "bid_amount": 830_000_000},
    )
    assert low_sim.status_code == 200
    assert high_sim.status_code == 200
    assert high_sim.json()["estimated_win_probability"] > low_sim.json()["estimated_win_probability"]
    assert low_sim.json()["expected_net_profit"] > high_sim.json()["expected_net_profit"]

    # 2. 신규 낙찰 결과 등록 E2E 검증
    test_case_no = "2026타경999999"
    rec_res = client.post(
        "/api/history/record",
        json={
            "case_no": test_case_no,
            "court_name": "서울서부지방법원",
            "property_type": "아파트",
            "region_name": "서울 마포구 아현동",
            "exclusive_area_m2": 59.9,
            "building_age_years": 10,
            "is_redev_zone": True,
            "unpaid_mgmt_fee": 400_000,
            "failed_count": 1,
            "appraisal_price": 900_000_000,
            "min_bid_price": 720_000_000,
            "market_value_at_bid": 920_000_000,
            "official_price": 650_000_000,
            "winning_bid_price": 810_000_000,
            "bidders_count": 9,
            "sold_date": "2026-10-18",
        },
    )
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["ok"] is True
    assert rec_data["recorded_case_no"] == test_case_no
    assert rec_data["winning_bid_ratio_appraisal"] == 90.0

    # MySQL DB에 실제 저장되었는지 확인 후 테스트 레코드 클린업
    hist_list = client.get("/api/history").json()
    assert any(h["case_no"] == test_case_no for h in hist_list)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM winning_bid_history WHERE case_no = %s", (test_case_no,))
        conn.commit()


def test_e2e_4_telegram_bot2_interactive_routing() -> None:
    """E2E 4: 텔레그램 Bot 2 (@gurucrabsss_bot) 인라인 콜백 및 텍스트 시뮬레이션 라우터 E2E 검증"""
    for cb_data in (
        "menu:home",
        "menu:attractive",
        "menu:redev",
        "menu:zerogap",
        "menu:history",
        "prop:2026타경104821",
        "detail6:2026타경104821",
        "rights:2026타경104821",
        "sim:2026타경104821:opt",
    ):
        text, kb = bot_poller.route_callback(cb_data)
        assert len(text) > 20
        assert "inline_keyboard" in kb

    sim_text, sim_kb = bot_poller.route_message_text("2026타경104821 79500")
    assert "7억 9,500만원" in sim_text
    assert "inline_keyboard" in sim_kb


def test_e2e_5_live_running_server_http_verification() -> None:
    """E2E 5: 실제 기동 중인 8000번 포트 AuctionRadar 데몬 서버에 실제 HTTP 요청을 보내 응답 검증"""
    with httpx.Client(base_url=LIVE_BASE_URL, timeout=15.0) as http_client:
        r_dash = http_client.get("/")
        assert r_dash.status_code == 200
        assert "AuctionRadar" in r_dash.text
        assert "2026타경104821" in r_dash.text

        r_cron = http_client.get("/api/cron/status")
        assert r_cron.status_code == 200
        cron_data = r_cron.json()
        assert cron_data["scheduler_running"] is True
        assert cron_data["job_id"] == "weekly_auction_scrape_notify"

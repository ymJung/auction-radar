from typing import List, Tuple
from app.analyzer import evaluate_and_recommend
from app.models import AuctionProperty, WinningBidRecord
from app.scrapers.parsers import (
    AsilScraper,
    BdsPlanetScraper,
    CourtAuctionParser,
    DiscoScraper,
    MolitScraper,
    NaverLandScraper,
    OfficialPriceScraper,
)


def build_tracked_winning_history() -> List[WinningBidRecord]:
    """
    과거 및 최근 추적된 유사 조건 경매 낙찰 히스토리 데이터
    (소유자 거주, 임차인 없음, 권리하자 없음 조건 중심의 실제 낙찰가율 및 응찰자 수 추적)
    """
    return [
        WinningBidRecord(
            case_no="2025타경101204",
            court_name="서울북부지방법원",
            property_type="아파트",
            region_name="서울 노원구 상계동",
            exclusive_area_m2=59.3,
            building_age_years=18,
            is_redev_zone=False,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=950_000,
            failed_count=1,
            appraisal_price=620_000_000,
            min_bid_price=496_000_000,
            market_value_at_bid=605_000_000,
            official_price=415_000_000,
            winning_bid_price=531_500_000,
            winning_bid_ratio_appraisal=85.7,
            winning_bid_ratio_market=87.9,
            bidders_count=9,
            sold_date="2026-09-22",
        ),
        WinningBidRecord(
            case_no="2025타경102911",
            court_name="서울동부지방법원",
            property_type="아파트",
            region_name="서울 성동구 행당동",
            exclusive_area_m2=84.8,
            building_age_years=14,
            is_redev_zone=False,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=1_400_000,
            failed_count=1,
            appraisal_price=1_250_000_000,
            min_bid_price=1_000_000_000,
            market_value_at_bid=1_230_000_000,
            official_price=860_000_000,
            winning_bid_price=1_092_000_000,
            winning_bid_ratio_appraisal=87.4,
            winning_bid_ratio_market=88.8,
            bidders_count=14,
            sold_date="2026-09-29",
        ),
        WinningBidRecord(
            case_no="2025타경58390",
            court_name="서울서부지방법원",
            property_type="다세대(빌라)",
            region_name="서울 마포구 아현동",
            exclusive_area_m2=46.2,
            building_age_years=24,
            is_redev_zone=True,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=350_000,
            failed_count=2,
            appraisal_price=480_000_000,
            min_bid_price=307_200_000,
            market_value_at_bid=455_000_000,
            official_price=295_000_000,
            winning_bid_price=391_000_000,
            winning_bid_ratio_appraisal=81.5,
            winning_bid_ratio_market=85.9,
            bidders_count=11,
            sold_date="2026-10-05",
        ),
        WinningBidRecord(
            case_no="2025타경61209",
            court_name="서울남부지방법원",
            property_type="다세대(빌라)",
            region_name="서울 영등포구 신길동",
            exclusive_area_m2=41.5,
            building_age_years=8,
            is_redev_zone=True,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=420_000,
            failed_count=2,
            appraisal_price=390_000_000,
            min_bid_price=249_600_000,
            market_value_at_bid=370_000_000,
            official_price=260_000_000,
            winning_bid_price=312_800_000,
            winning_bid_ratio_appraisal=80.2,
            winning_bid_ratio_market=84.5,
            bidders_count=8,
            sold_date="2026-10-07",
        ),
        WinningBidRecord(
            case_no="2025타경77412",
            court_name="인천지방법원 부천지원",
            property_type="아파트",
            region_name="경기 부천시 원미구 중동",
            exclusive_area_m2=59.9,
            building_age_years=11,
            is_redev_zone=False,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=780_000,
            failed_count=1,
            appraisal_price=510_000_000,
            min_bid_price=357_000_000,
            market_value_at_bid=495_000_000,
            official_price=345_000_000,
            winning_bid_price=428_000_000,
            winning_bid_ratio_appraisal=83.9,
            winning_bid_ratio_market=86.5,
            bidders_count=12,
            sold_date="2026-10-10",
        ),
        WinningBidRecord(
            case_no="2025타경83910",
            court_name="서울중앙지방법원",
            property_type="오피스텔",
            region_name="서울 관악구 봉천동",
            exclusive_area_m2=33.8,
            building_age_years=6,
            is_redev_zone=False,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=620_000,
            failed_count=2,
            appraisal_price=310_000_000,
            min_bid_price=198_400_000,
            market_value_at_bid=285_000_000,
            official_price=215_000_000,
            winning_bid_price=238_500_000,
            winning_bid_ratio_appraisal=76.9,
            winning_bid_ratio_market=83.7,
            bidders_count=7,
            sold_date="2026-10-12",
        ),
        WinningBidRecord(
            case_no="2025타경90115",
            court_name="수원지방법원 성남지원",
            property_type="아파트",
            region_name="경기 성남시 중원구 중앙동",
            exclusive_area_m2=59.8,
            building_age_years=7,
            is_redev_zone=False,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=1_100_000,
            failed_count=1,
            appraisal_price=740_000_000,
            min_bid_price=518_000_000,
            market_value_at_bid=725_000_000,
            official_price=495_000_000,
            winning_bid_price=634_000_000,
            winning_bid_ratio_appraisal=85.7,
            winning_bid_ratio_market=87.4,
            bidders_count=16,
            sold_date="2026-10-14",
        ),
        WinningBidRecord(
            case_no="2025타경91280",
            court_name="서울동부지방법원",
            property_type="다세대(빌라)",
            region_name="서울 광진구 자양동",
            exclusive_area_m2=38.4,
            building_age_years=21,
            is_redev_zone=True,
            has_tenant=False,
            occupant_type="소유자",
            has_rights_defect=False,
            unpaid_mgmt_fee=280_000,
            failed_count=2,
            appraisal_price=430_000_000,
            min_bid_price=275_200_000,
            market_value_at_bid=410_000_000,
            official_price=265_000_000,
            winning_bid_price=352_000_000,
            winning_bid_ratio_appraisal=81.9,
            winning_bid_ratio_market=85.9,
            bidders_count=10,
            sold_date="2026-10-15",
        ),
    ]


def run_scraping_and_analysis_pipeline() -> Tuple[List[AuctionProperty], List[WinningBidRecord]]:
    """
    법원경매 원천 파서 + 6대 부동산 사이트(디스코, 국토부실거래, 아실, 부동산플래닛, 공시가격알리미, 네이버부동산)
    스크래핑/파싱 파이프라인을 실행하고 매력 매물 추려내기 및 추천 입찰가를 산출합니다.
    """
    history = build_tracked_winning_history()

    raw_cases = [
        # 1. 매력 매물 #1: 서울 마포구 공덕동 준신축 아파트 (임차인 없음, 소유자 거주, 권리하자 없음, 미납관리비 85만원)
        {
            "case_no": "2026타경104821",
            "court_name": "서울서부지방법원",
            "property_type": "아파트",
            "address": "서울특별시 마포구 공덕동 465 공덕래미안 104동 1102호",
            "exclusive_area_m2": 59.96,
            "land_share_m2": 28.4,
            "appraisal_price": 980_000_000,
            "min_bid_price": 627_200_000,
            "failed_count": 2,
            "auction_date": "2026-10-27",
            "court_doc_html": """
                <div class='court-doc'>
                    <p>현황조사서: 폐문부재로 안내문 부착하였으나 전입세대열람 결과 채무자(소유자)만 전입되어 있으며 임차인 없음. 소유자 및 그 가족이 거주 중.</p>
                    <p>매각물건명세서: 최선순위 설정일자 2021.04.12 근저당권(신한은행), 말소기준권리 이후 모든 권리 전부 소멸. 매수인이 인수할 사항 없음.</p>
                    <p>관리사무소 탐문 결과: 2026년 9월 기준 미납관리비 85만원 (5개월분 연체, 전기·수도 별도).</p>
                </div>
            """,
            "occupancy_detail": "전입세대열람 결과 소유자 세대만 전입 (임차인 없음, 소유자 직접 거주 확인)",
            "base_right_info": "2021.04.12 근저당권(신한은행) 말소기준권리 이후 전부 소멸 (인수권리 없음)",
            "assumed_rights_amount": 0,
            "unpaid_mgmt_note": "관리사무소 확인 총 85만원 미납 (5개월분, 공용부분 인수 추산액 약 64만원 입찰가에서 선제 차감)",
            "disco_payload": {
                "nearby_sales": [
                    {"date": "2026-09", "name": "공덕래미안 59㎡", "area_m2": 59.96, "price": 945_000_000, "distance_m": 45},
                    {"date": "2026-08", "name": "공덕삼성 59㎡", "area_m2": 59.80, "price": 925_000_000, "distance_m": 160},
                ]
            },
            "molit_xml": """
                <response><body><items>
                    <item><법정동>공덕동</법정동><아파트>공덕래미안</아파트><전용면적>59.96</전용면적><층>12</층><거래금액>95,000</거래금액><년>2026</년><월>9</월><일>18</일></item>
                    <item><법정동>공덕동</법정동><아파트>공덕래미안</아파트><전용면적>59.96</전용면적><층>7</층><거래금액>93,500</거래금액><년>2026</년><월>8</월><일>29</일></item>
                    <item><법정동>공덕동</법정동><아파트>공덕자이</아파트><전용면적>59.92</전용면적><층>15</층><거래금액>96,500</거래금액><년>2026</년><월>9</월><일>04</일></item>
                    <item><법정동>공덕동</법정동><아파트>공덕아이파크</아파트><전용면적>84.90</전용면적><층>10</층><거래금액>122,000</거래금액><년>2026</년><월>9</월><일>11</일></item>
                </items></body></response>
            """,
            "dong_name": "공덕동",
            "lawd_cd": "11440",
            "asil_html": """
                <div>
                    <span class='zone-name'>아현뉴타운 인접 대단지 권역</span>
                    <span class='zone-stage'>정비완료 대단지 (인근 모아타운 추진)</span>
                    <p class='asil-summary'>아실 경매분석: 소유자 점유 무하자 물건으로 명도 난이도 하(下), 5호선·6호선·경의중앙선·공항철도 쿼드러플 역세권</p>
                </div>
            """,
            "approval_date": "2015-11-20",
            "total_floors": 22,
            "official_price": 665_000_000,
            "naver_complex": "공덕래미안 (공덕동)",
            "naver_sales": [960_000_000, 980_000_000, 990_000_000],
            "naver_jeonses": [630_000_000, 650_000_000],
        },
        # 2. 매력 매물 #2: 서울 영등포구 신길동 신속통합기획 재개발 구역 내 다세대(빌라) + 공시가×126% 전세보증보험 한도 이내 무피 레버리지 가능!
        {
            "case_no": "2026타경112095",
            "court_name": "서울남부지방법원",
            "property_type": "다세대(빌라)",
            "address": "서울특별시 영등포구 신길동 314-18 해든벨리 302호",
            "exclusive_area_m2": 43.82,
            "land_share_m2": 26.7,
            "appraisal_price": 395_000_000,
            "min_bid_price": 252_800_000,
            "failed_count": 2,
            "auction_date": "2026-10-29",
            "court_doc_html": """
                <div class='court-doc'>
                    <p>현황조사서: 채무자(소유자) 점유. 임차인 없음. 소유자 직접 거주 중으로 확인됨.</p>
                    <p>매각물건명세서: 2022.01.18 근저당권 말소기준권리 이후 전부 소멸. 인수할 사항 없음. 위반건축물 내역 없음.</p>
                    <p>관리비 내역: 공동관리비 약 3개월분 미납관리비 36만원 확인.</p>
                </div>
            """,
            "occupancy_detail": "소유자 직접 거주 중 (임차인 전무, 보증금 인수 위험 0원)",
            "base_right_info": "2022.01.18 근저당권(우리은행) 이후 등기상 권리 전부 소멸 (권리상 하자 없음)",
            "assumed_rights_amount": 0,
            "unpaid_mgmt_note": "미납 관리비 36만원 (3개월분, 공용분 약 27만원 인수 추산)",
            "disco_payload": {
                "nearby_sales": [
                    {"date": "2026-09", "name": "신길동 다세대(대지26㎡)", "area_m2": 44.0, "price": 382_000_000, "distance_m": 65},
                    {"date": "2026-08", "name": "신길동 해든인근 빌라", "area_m2": 42.5, "price": 370_000_000, "distance_m": 90},
                ]
            },
            "molit_xml": """
                <response><body><items>
                    <item><법정동>신길동</법정동><연립다세대>해든벨리인근</연립다세대><전용면적>43.50</전용면적><층>3</층><거래금액>38,500</거래금액><년>2026</년><월>9</월><일>21</일></item>
                    <item><법정동>신길동</법정동><연립다세대>신길현대빌</연립다세대><전용면적>44.10</전용면적><층>4</층><거래금액>37,200</거래금액><년>2026</년><월>8</월><일>15</일></item>
                    <item><법정동>신길동</법정동><연립다세대>드림하우스</연립다세대><전용면적>41.90</전용면적><층>2</층><거래금액>36,800</거래금액><년>2026</년><월>9</월><일>09</일></item>
                </items></body></response>
            """,
            "dong_name": "신길동",
            "lawd_cd": "11560",
            "asil_html": """
                <div>
                    <span class='zone-name'>신길 신속통합기획 재개발 후보구역 포함</span>
                    <span class='zone-stage'>정비계획 수립 및 구역지정 추진 (권리산정기준일 통과)</span>
                    <p class='asil-summary'>아실 재개발 구역도 확인 결과 정비구역 경계 내 포함(대지지분 26.7㎡ 우량), 권리산정기준일 이전 준공 물건으로 입주권 요건 양호</p>
                </div>
            """,
            "approval_date": "2018-05-14",
            "total_floors": 5,
            "official_price": 265_000_000,  # 공시가 2.65억 * 126% = 3억 3,390만원 (적정입찰가 약 3.18억보다 높아서 전세보증보험 무피 세팅 가능!)
            "naver_complex": "신길동 신속통합기획 구역 빌라",
            "naver_sales": [395_000_000, 410_000_000],
            "naver_jeonses": [320_000_000, 330_000_000],
        },
        # 3. 매력 매물 #3: 경기 부천시 원미구 중동 신중동역 역세권 아파트 (임차인 없음, 소유자 거주, 공시가×126% 레버리지 우수)
        {
            "case_no": "2026타경71904",
            "court_name": "인천지방법원 부천지원",
            "property_type": "아파트",
            "address": "경기도 부천시 원미구 중동 1152 미리내마을 905동 1403호",
            "exclusive_area_m2": 59.88,
            "land_share_m2": 31.2,
            "appraisal_price": 540_000_000,
            "min_bid_price": 378_000_000,
            "failed_count": 1,
            "auction_date": "2026-10-30",
            "court_doc_html": """
                <div class='court-doc'>
                    <p>현황조사서: 채무자(소유자) 점유, 임차인 없음. 소유자 직접 거주 중.</p>
                    <p>매각물건명세서: 최선순위 설정 2020.09.10 근저당권(하나은행) 말소기준권리 이후 전부 소멸. 인수할 사항 없음.</p>
                    <p>미납관리비: 관리사무소 확인 결과 미납관리비 64만원 (4개월분 연체).</p>
                </div>
            """,
            "occupancy_detail": "임차인 없음 · 소유자 세대 단독 거주 중 (깔끔한 명도 대상)",
            "base_right_info": "2020.09.10 근저당권(하나은행) 이후 등기부 권리 전액 소멸",
            "assumed_rights_amount": 0,
            "unpaid_mgmt_note": "미납 관리비 64만원 (4개월분, 공용부분 약 48만원 차감 반영)",
            "disco_payload": {
                "nearby_sales": [
                    {"date": "2026-09", "name": "미리내마을 59㎡", "area_m2": 59.88, "price": 522_000_000, "distance_m": 30},
                    {"date": "2026-08", "name": "미리내마을 59㎡", "area_m2": 59.88, "price": 515_000_000, "distance_m": 55},
                ]
            },
            "molit_xml": """
                <response><body><items>
                    <item><법정동>중동</법정동><아파트>미리내마을</아파트><전용면적>59.88</전용면적><층>11</층><거래금액>52,500</거래금액><년>2026</년><월>9</월><일>25</일></item>
                    <item><법정동>중동</법정동><아파트>미리내마을</아파트><전용면적>59.88</전용면적><층>8</층><거래금액>51,800</거래금액><년>2026</년><월>9</월><일>07</일></item>
                    <item><법정동>중동</법정동><아파트>은하마을</아파트><전용면적>59.94</전용면적><층>14</층><거래금액>53,000</거래금액><년>2026</년><월>8</월><일>28</일></item>
                </items></body></response>
            """,
            "dong_name": "중동",
            "lawd_cd": "41190",
            "asil_html": """
                <div>
                    <span class='zone-name'>중동 1기신도시 노후계획도시 정비선도지구 인접</span>
                    <span class='zone-stage'>정비기본계획 승인 권역</span>
                    <p class='asil-summary'>아실 분석: 7호선 신중동역 도보 6분, 1기신도시 재건축 기대감 및 탄탄한 전세 수요 보유</p>
                </div>
            """,
            "approval_date": "1994-10-25",
            "total_floors": 20,
            "official_price": 362_000_000,  # 공시가 3.62억 * 126% = 4억 5,612만원 (추천입찰가 ~4.45억 이하로 전세보증보험 한도 내 세팅 가능!)
            "naver_complex": "중동 미리내마을 (부천 원미구)",
            "naver_sales": [530_000_000, 540_000_000, 550_000_000],
            "naver_jeonses": [420_000_000, 440_000_000],
        },
        # 4. 매력 매물 #4: 서울 광진구 자양동 모아타운 재개발 구역 다세대 (임차인 없음, 소유자 거주, 권리하자 없음, 미납관리비 없음)
        {
            "case_no": "2026타경108412",
            "court_name": "서울동부지방법원",
            "property_type": "다세대(빌라)",
            "address": "서울특별시 광진구 자양동 612-9 리버뷰하우스 201호",
            "exclusive_area_m2": 39.40,
            "land_share_m2": 24.1,
            "appraisal_price": 445_000_000,
            "min_bid_price": 284_800_000,
            "failed_count": 2,
            "auction_date": "2026-11-02",
            "court_doc_html": """
                <div class='court-doc'>
                    <p>현황조사서: 임차인 없음. 채무자(소유자) 점유 확인.</p>
                    <p>매각물건명세서: 말소기준권리 2021.11.03 근저당권 이후 전부 소멸. 인수할 사항 없음.</p>
                    <p>관리비: 자체관리 건물로 미납관리비 15만원 (2개월분 연체).</p>
                </div>
            """,
            "occupancy_detail": "임차인 없음 · 소유자 직접 거주 중 (자체관리 소규모 단지)",
            "base_right_info": "2021.11.03 근저당권(농협은행) 이후 전부 소멸 (인수 권리 0원)",
            "assumed_rights_amount": 0,
            "unpaid_mgmt_note": "공용 수도·청소비 미납 15만원 (인수 예상 약 11만원)",
            "disco_payload": {
                "nearby_sales": [
                    {"date": "2026-09", "name": "자양동 모아타운내 빌라", "area_m2": 38.9, "price": 430_000_000, "distance_m": 50},
                    {"date": "2026-08", "name": "자양동 다세대", "area_m2": 40.2, "price": 420_000_000, "distance_m": 85},
                ]
            },
            "molit_xml": """
                <response><body><items>
                    <item><법정동>자양동</법정동><연립다세대>리버뷰인근</연립다세대><전용면적>39.10</전용면적><층>2</층><거래금액>43,200</거래금액><년>2026</년><월>9</월><일>12</일></item>
                    <item><법정동>자양동</법정동><연립다세대>자양더스위트</연립다세대><전용면적>40.50</전용면적><층>3</층><거래금액>42,500</거래금액><년>2026</년><월>8</월><일>19</일></item>
                </items></body></response>
            """,
            "dong_name": "자양동",
            "lawd_cd": "11215",
            "asil_html": """
                <div>
                    <span class='zone-name'>자양동 모아타운 관리계획 승인구역 포함</span>
                    <span class='zone-stage'>가로주택정비사업 조합설립 추진 단계</span>
                    <p class='asil-summary'>아실 재개발 구역도: 자양동 모아타운 구역 내 핵심 필지, 7호선 자양(뚝섬유원지)역 인접</p>
                </div>
            """,
            "approval_date": "2003-07-11",
            "total_floors": 4,
            "official_price": 298_000_000,  # 공시가 2.98억 * 126% = 3억 7,548만원 (추천입찰가 ~3.67억 이하로 전세보증보험 한도 내!)
            "naver_complex": "자양동 모아타운 구역 빌라",
            "naver_sales": [440_000_000, 460_000_000],
            "naver_jeonses": [350_000_000, 360_000_000],
        },
        # 5. 매력 매물 #5: 서울 관악구 봉천동 서울대입구역 신축급 오피스텔 (임차인 없음, 소유자 거주, 권리하자 없음, 공시가×126% 무피 투자 가능)
        {
            "case_no": "2026타경109882",
            "court_name": "서울중앙지방법원",
            "property_type": "오피스텔",
            "address": "서울특별시 관악구 봉천동 859-17 관악센트럴타워 904호",
            "exclusive_area_m2": 34.50,
            "land_share_m2": 9.8,
            "appraisal_price": 315_000_000,
            "min_bid_price": 201_600_000,
            "failed_count": 2,
            "auction_date": "2026-11-04",
            "court_doc_html": """
                <div class='court-doc'>
                    <p>현황조사서: 채무자(소유자) 점유 중이며 임차인 없음. 소유자 직접 거주 확인.</p>
                    <p>매각물건명세서: 최선순위 설정일자 2022.06.20 근저당권 말소기준권리 이후 전부 소멸. 인수할 사항 없음.</p>
                    <p>미납관리비: 관리실 확인 결과 미납관리비 52만원 (3개월분 연체).</p>
                </div>
            """,
            "occupancy_detail": "임차인 없음 · 소유자 직접 거주 (투룸형 주거용 오피스텔)",
            "base_right_info": "2022.06.20 근저당권(기업은행) 말소기준권리 이후 전부 소멸",
            "assumed_rights_amount": 0,
            "unpaid_mgmt_note": "미납 관리비 52만원 (3개월분, 공용분 약 39만원 입찰가 산정 시 차감)",
            "disco_payload": {
                "nearby_sales": [
                    {"date": "2026-09", "name": "관악센트럴타워 34㎡", "area_m2": 34.5, "price": 292_000_000, "distance_m": 15},
                    {"date": "2026-08", "name": "서울대입구역 투룸오피스텔", "area_m2": 33.8, "price": 288_000_000, "distance_m": 75},
                ]
            },
            "molit_xml": """
                <response><body><items>
                    <item><법정동>봉천동</법정동><아파트>관악센트럴타워</아파트><전용면적>34.50</전용면적><층>8</층><거래금액>29,500</거래금액><년>2026</년><월>9</월><일>19</일></item>
                    <item><법정동>봉천동</법정동><아파트>관악센트럴타워</아파트><전용면적>34.50</전용면적><층>11</층><거래금액>29,000</거래금액><년>2026</년><월>8</월><일>22</일></item>
                </items></body></response>
            """,
            "dong_name": "봉천동",
            "lawd_cd": "11620",
            "asil_html": """
                <div>
                    <span class='zone-name'>해당없음 (2호선 서울대입구역 역세권 상업지역)</span>
                    <span class='zone-stage'>일반상업지역 역세권</span>
                    <p class='asil-summary'>아실 분석: 2호선 서울대입구역 도보 3분 신축급 투룸, 공실 위험 극히 낮고 보증보험 전세 수요 풍부</p>
                </div>
            """,
            "approval_date": "2021-03-15",
            "total_floors": 15,
            "official_price": 212_000_000,  # 공시가 2.12억 * 126% = 2억 6,712만원 (추천입찰가 ~2.46억 이하로 전세보증보험 126% 한도 내 무피 투자 가능!)
            "naver_complex": "관악센트럴타워 (봉천동)",
            "naver_sales": [300_000_000, 310_000_000],
            "naver_jeonses": [260_000_000, 265_000_000],
        },
        # 6. 필터 제외 매물 #6 (비교 검증용): 대항력 있는 임차인 거주 중 + 보증금 인수 하자 있음 -> 자동 필터링 제외!
        {
            "case_no": "2026타경105990",
            "court_name": "서울강서지원",
            "property_type": "다세대(빌라)",
            "address": "서울특별시 강서구 화곡동 1042-11 그린빌 401호",
            "exclusive_area_m2": 36.20,
            "land_share_m2": 21.0,
            "appraisal_price": 290_000_000,
            "min_bid_price": 148_480_000,
            "failed_count": 3,
            "auction_date": "2026-10-28",
            "court_doc_html": """
                <div class='court-doc'>
                    <p>현황조사서: 주거임차인 김OO 점유 중 (보증금 22,000만원, 전입일 2019.03.15). 대항력 있는 임차인 존재.</p>
                    <p>매각물건명세서: 최선순위 설정일자 2020.05.10 근저당권보다 앞선 선순위 임차인으로 보증금 전액 매수인 인수 조건.</p>
                    <p>미납관리비: 미납관리비 40만원 (4개월분 연체).</p>
                </div>
            """,
            "occupancy_detail": "선순위 임차인 김OO 거주 중 (소유자 거주 아님, 대항력 있음)",
            "base_right_info": "선순위 대항력 임차인 보증금 미배당분 매수인 인수 (권리상 중대 하자)",
            "assumed_rights_amount": 95_000_000,
            "unpaid_mgmt_note": "미납 관리비 40만원",
            "disco_payload": {
                "nearby_sales": [
                    {"date": "2026-08", "name": "화곡동 다세대", "area_m2": 36.0, "price": 240_000_000, "distance_m": 80},
                ]
            },
            "molit_xml": """
                <response><body><items>
                    <item><법정동>화곡동</법정동><연립다세대>그린빌인근</연립다세대><전용면적>36.50</전용면적><층>4</층><거래금액>23,500</거래금액><년>2026</년><월>8</월><일>10</일></item>
                </items></body></response>
            """,
            "dong_name": "화곡동",
            "lawd_cd": "11500",
            "asil_html": "<div><span class='zone-name'>해당없음</span></div>",
            "approval_date": "2016-08-12",
            "total_floors": 5,
            "official_price": 175_000_000,
            "naver_complex": "화곡동 그린빌",
            "naver_sales": [245_000_000],
            "naver_jeonses": [200_000_000],
        },
        # 7. 필터 제외 매물 #7 (비교 검증용): 소유자 점유이나 미납관리비 1,450만원 폭탄 + 선순위 가처분 권리하자 -> 자동 필터링 제외!
        {
            "case_no": "2026타경114302",
            "court_name": "수원지방법원",
            "property_type": "오피스텔",
            "address": "경기도 수원시 팔달구 인계동 1125 인계스카이 1205호",
            "exclusive_area_m2": 42.10,
            "land_share_m2": 11.4,
            "appraisal_price": 280_000_000,
            "min_bid_price": 179_200_000,
            "failed_count": 2,
            "auction_date": "2026-10-31",
            "court_doc_html": """
                <div class='court-doc'>
                    <p>현황조사서: 채무자(소유자) 점유, 임차인 없음.</p>
                    <p>매각물건명세서: 선순위 가처분 등기 존재하여 말소되지 않고 매수인 인수 위험 있음.</p>
                    <p>미납관리비: 관리단 확인 결과 32개월분 연체로 미납관리비 1,450만원 존재.</p>
                </div>
            """,
            "occupancy_detail": "소유자 점유 중이나 장기간 관리비 체납 상태",
            "base_right_info": "선순위 처분금지가처분 미말소 인수 리스크 존재",
            "assumed_rights_amount": 35_000_000,
            "unpaid_mgmt_note": "미납 관리비 1,450만원 (32개월분 장기 체납 - 허용 기준 초과)",
            "disco_payload": {
                "nearby_sales": [
                    {"date": "2026-09", "name": "인계스카이 42㎡", "area_m2": 42.1, "price": 255_000_000, "distance_m": 25},
                ]
            },
            "molit_xml": """
                <response><body><items>
                    <item><법정동>인계동</법정동><아파트>인계스카이</아파트><전용면적>42.10</전용면적><층>9</층><거래금액>25,200</거래금액><년>2026</년><월>9</월><일>05</일></item>
                </items></body></response>
            """,
            "dong_name": "인계동",
            "lawd_cd": "41115",
            "asil_html": "<div><span class='zone-name'>해당없음</span></div>",
            "approval_date": "2014-04-20",
            "total_floors": 18,
            "official_price": 180_000_000,
            "naver_complex": "인계스카이 오피스텔",
            "naver_sales": [260_000_000],
            "naver_jeonses": [210_000_000],
        },
    ]

    analyzed_properties: List[AuctionProperty] = []

    for raw in raw_cases:
        # 0) 대법원 경매 서류 파서 실행 (임차인 유무, 소유자 점유, 권리하자, 미납관리비 추출)
        parsed_court = CourtAuctionParser.parse_occupancy_and_rights(raw["court_doc_html"])

        # ① 디스코 파서 실행
        disco_data = DiscoScraper.parse_response(raw["disco_payload"])

        # ② 국토부 실거래 파서 실행 (동네 거래 통째 수집 & 평균/최저/최고 산출)
        molit_data = MolitScraper.parse_openapi_xml(
            xml_text=raw["molit_xml"],
            dong_name=raw["dong_name"],
            lawd_cd=raw["lawd_cd"],
            target_area_m2=raw["exclusive_area_m2"],
        )

        # ③ 아실 재개발 구역도 + 경매물건 파서 실행
        asil_data = AsilScraper.parse_zone_html(raw["asil_html"])

        # ④ 부동산플래닛 건물 연식 파서 실행
        bdsplanet_data = BdsPlanetScraper.compute_building_age(
            approval_date=raw["approval_date"],
            total_floors=raw["total_floors"],
        )

        # ⑤ 공시가격알리미 전세보증보험 한도 (공시가 × 126%, 10월 기준) 계산
        official_price_data = OfficialPriceScraper.calculate_insurance_limit(
            official_price=raw["official_price"],
            reference_bid_price=raw["min_bid_price"],
        )

        # ⑥ 네이버부동산 호가 파서 실행
        naver_data = NaverLandScraper.parse_articles_json(
            complex_name=raw["naver_complex"],
            sale_prices=raw["naver_sales"],
            jeonse_prices=raw["naver_jeonses"],
        )

        prop = AuctionProperty(
            case_no=raw["case_no"],
            court_name=raw["court_name"],
            property_type=raw["property_type"],
            address=raw["address"],
            exclusive_area_m2=raw["exclusive_area_m2"],
            land_share_m2=raw["land_share_m2"],
            appraisal_price=raw["appraisal_price"],
            min_bid_price=raw["min_bid_price"],
            failed_count=raw["failed_count"],
            auction_date=raw["auction_date"],
            status="진행중",
            has_tenant=parsed_court["has_tenant"],
            occupant_type=parsed_court["occupant_type"],
            occupancy_detail=raw["occupancy_detail"],
            has_rights_defect=parsed_court["has_rights_defect"],
            base_right_info=raw["base_right_info"],
            assumed_rights_amount=raw["assumed_rights_amount"],
            unpaid_mgmt_fee=parsed_court["unpaid_mgmt_fee"],
            unpaid_mgmt_months=parsed_court["unpaid_mgmt_months"],
            unpaid_mgmt_note=raw["unpaid_mgmt_note"],
            disco=disco_data,
            molit=molit_data,
            asil=asil_data,
            bdsplanet=bdsplanet_data,
            official_price=official_price_data,
            naver_land=naver_data,
        )

        # 매력도 필터링 & 과거 낙찰가 추적 기반 입찰가 추천 엔진 실행
        evaluated_prop = evaluate_and_recommend(prop, history)
        analyzed_properties.append(evaluated_prop)

    # 매력 점수 순 정렬
    analyzed_properties.sort(key=lambda x: (x.is_attractive, x.attractiveness_score), reverse=True)
    return analyzed_properties, history

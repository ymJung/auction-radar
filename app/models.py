from typing import List, Optional
from pydantic import BaseModel, Field


class DiscoData(BaseModel):
    """① 디스코: 지도에서 실제 팔린 가격 (인근 매각/실거래 데이터)"""
    nearby_sold_price_avg: int = Field(..., description="지도 반경 내 유사 매물 실제 매각가 평균(원)")
    recent_sold_case: str = Field(..., description="최근 인근 실제 매각 사례 요약")
    price_per_pyeong: int = Field(..., description="인근 실거래 평당가(원)")
    distance_m: int = Field(default=120, description="기준 매물과의 거리(m)")
    source_url: str = Field(default="https://www.disco.re", description="디스코 지도 참조 링크")


class MolitTransactionItem(BaseModel):
    """국토부 실거래 개별 거래 건"""
    contract_date: str
    building_name: str
    exclusive_area_m2: float
    floor: int
    deal_amount: int  # 원 단위


class MolitData(BaseModel):
    """② 국토부 실거래: 그 동네 거래 통째로 받기"""
    dong_name: str = Field(..., description="법정동 명칭")
    lawd_cd: str = Field(..., description="법정동 코드(5자리)")
    total_tx_count: int = Field(..., description="최근 수집된 동네 전체 거래 건수")
    similar_area_avg_price: int = Field(..., description="동일/유사 면적 실거래 평균가(원)")
    min_deal_price: int = Field(..., description="동네 유사 면적 최저 실거래가(원)")
    max_deal_price: int = Field(..., description="동네 유사 면적 최고 실거래가(원)")
    recent_trend: str = Field(..., description="동네 실거래 추세 (상승/보합/강보합 등)")
    transactions: List[MolitTransactionItem] = Field(default_factory=list, description="동네 실거래 표본 목록")
    source_url: str = Field(default="https://rt.molit.go.kr", description="국토부 실거래가 공개시스템")


class AsilData(BaseModel):
    """③ 아실: 재개발 구역도 + 경매물건"""
    is_redev_zone: bool = Field(..., description="재개발/재건축/정비구역 포함 또는 인접 여부")
    redev_zone_name: str = Field(..., description="정비구역 명칭 (예: 신속통합기획 2차 후보지, 모아타운, 해당없음)")
    redev_stage: str = Field(..., description="진행 단계 (예: 구역지정, 조합설립인가, 사업시행인가, 해당없음)")
    asil_case_summary: str = Field(..., description="아실 경매물건 권리/입지 코멘트")
    source_url: str = Field(default="https://asil.kr", description="아실 참조 링크")


class BdsPlanetData(BaseModel):
    """④ 부동산플래닛: 건물이 몇 년 됐는지 (준공연도/노후도)"""
    approval_date: str = Field(..., description="사용승인일 (YYYY-MM-DD)")
    built_year: int = Field(..., description="준공연도")
    building_age_years: int = Field(..., description="건물 연식 (2026년 기준 몇 년 됐는지)")
    total_floors: int = Field(..., description="건물 총 층수")
    structure_type: str = Field(default="철근콘크리트조", description="주구조")
    age_condition_grade: str = Field(..., description="연식 상태 등급 (신축급/준신축/구축/노후-재개발기대)")
    source_url: str = Field(default="https://www.bdsplanet.com", description="부동산플래닛 링크")


class OfficialPriceData(BaseModel):
    """⑤ 공시가격알리미: 전세보증보험 한도 (공시가 × 126%, 10월 기준)"""
    official_price: int = Field(..., description="공동/개별주택 공시가격(원)")
    reference_year: int = Field(default=2026, description="공시 기준연도")
    rule_multiplier: float = Field(default=1.26, description="전세보증보험 산정 배수 (126%, 10월 기준)")
    jeonse_insurance_limit: int = Field(..., description="전세보증보험 가입 한도 (공시가 × 126%, 원)")
    can_zero_gap_invest: bool = Field(..., description="추천 입찰가가 전세보증보험 한도 이하인지 여부 (레버리지 용이성)")
    source_url: str = Field(default="https://www.realtyprice.kr", description="공시가격알리미 링크")


class NaverLandData(BaseModel):
    """⑥ 네이버부동산: 현재 시장 매매/전세 호가"""
    complex_or_area_name: str = Field(..., description="단지명 또는 인근 구역명")
    asking_sale_min: int = Field(..., description="현재 네이버부동산 매매 최저 호가(원)")
    asking_sale_avg: int = Field(..., description="현재 네이버부동산 매매 평균 호가(원)")
    asking_jeonse_avg: int = Field(..., description="현재 네이버부동산 전세 평균 호가(원)")
    active_listing_count: int = Field(..., description="현재 등록된 매물 수")
    source_url: str = Field(default="https://new.land.naver.com", description="네이버부동산 링크")


class BidRecommendation(BaseModel):
    """낙찰 추적 데이터 기반 입찰가 추천 결과"""
    conservative_bid: int = Field(..., description="안정형(보수적) 추천 입찰가(원) - 낙찰확률 약 40~45%")
    conservative_win_prob: float = Field(..., description="안정형 예상 낙찰 확률(%)")

    optimal_bid: int = Field(..., description="적정 추천 입찰가(원) - 낙찰확률 약 70%, 수익/확률 최적 균형")
    optimal_win_prob: float = Field(..., description="적정 추천가 예상 낙찰 확률(%)")
    optimal_ratio_to_appraisal: float = Field(..., description="적정 추천가의 감정가 대비 낙찰가율(%)")
    optimal_ratio_to_market: float = Field(..., description="적정 추천가의 실거래 시세 대비 비율(%)")

    aggressive_bid: int = Field(..., description="공격형(필승) 추천 입찰가(원) - 낙찰확률 약 88%+")
    aggressive_win_prob: float = Field(..., description="공격형 예상 낙찰 확률(%)")

    estimated_market_value: int = Field(..., description="6대 사이트 교차 분석 기반 추정 시세(원)")
    assumed_unpaid_mgmt_fee: int = Field(..., description="인수 예상 미납관리비(공용부분 중심 차감액, 원)")
    estimated_eviction_and_tax: int = Field(..., description="소유자 명도협의금 및 취득세/부대비용 추정액(원)")
    expected_net_profit: int = Field(..., description="적정 입찰가 낙찰 시 모든 비용(미납관리비 포함) 차감 후 예상 안전마진(원)")
    similar_cases_count: int = Field(..., description="참조한 유사 조건 과거 낙찰 추적 사례 수")
    rationale: List[str] = Field(default_factory=list, description="입찰가 산정 세부 근거")


class AuctionProperty(BaseModel):
    """경매 매물 통합 모델 (권리/점유/미납관리비 + 6대 사이트 데이터 + 낙찰추천)"""
    id: Optional[int] = None
    case_no: str = Field(..., description="사건번호 (예: 2025타경104821)")
    court_name: str = Field(..., description="관할법원")
    property_type: str = Field(..., description="물건종류 (아파트/오피스텔/다세대빌라/근린주택)")
    address: str = Field(..., description="소재지 주소")
    exclusive_area_m2: float = Field(..., description="전용면적(㎡)")
    land_share_m2: float = Field(default=0.0, description="대지권 면적(㎡)")

    appraisal_price: int = Field(..., description="감정가(원)")
    min_bid_price: int = Field(..., description="최저매각가격(원)")
    failed_count: int = Field(..., description="유찰 횟수")
    auction_date: str = Field(..., description="매각기일 (YYYY-MM-DD)")
    status: str = Field(default="진행중", description="진행상태 (진행중 / 낙찰 / 유찰)")

    # 핵심 필터 조건 1: 임차인 유무 & 소유자 거주 여부
    has_tenant: bool = Field(..., description="임차인 존재 여부 (False여야 매력 물건)")
    occupant_type: str = Field(..., description="점유자 유형 ('소유자', '임차인', '공실')")
    occupancy_detail: str = Field(..., description="현황조사서 점유관계 요약")

    # 핵심 필터 조건 2: 권리상 하자 여부
    has_rights_defect: bool = Field(..., description="권리상 인수 하자 존재 여부 (False여야 매력 물건)")
    base_right_info: str = Field(..., description="말소기준권리 및 소멸/인수 내역")
    assumed_rights_amount: int = Field(default=0, description="인수해야 할 권리 금액(원)")

    # 핵심 필터 조건 3: 미납 관리비
    unpaid_mgmt_fee: int = Field(default=0, description="확인/탐문된 총 미납 관리비(원)")
    unpaid_mgmt_months: int = Field(default=0, description="미납 개월 수")
    unpaid_mgmt_note: str = Field(default="", description="미납 관리비 상세 내역 및 공용관리비 인수 안내")

    # 6대 사이트 교차 분석 데이터
    disco: DiscoData
    molit: MolitData
    asil: AsilData
    bdsplanet: BdsPlanetData
    official_price: OfficialPriceData
    naver_land: NaverLandData

    # 매력도 판정 및 추천 입찰가
    is_attractive: bool = Field(default=False, description="사용자 핵심 조건(임차인無+소유자거주+권리하자無+관리비적정) 충족 여부")
    rejection_reasons: List[str] = Field(default_factory=list, description="조건 미충족 시 사유 목록")
    attractiveness_score: int = Field(default=0, description="매력도 종합 점수 (0~100)")
    recommendation: Optional[BidRecommendation] = None

    # 실제 낙찰 결과 추적 (낙찰 완료 시 기록)
    winning_bid_price: Optional[int] = Field(default=None, description="실제 낙찰가(원)")
    winning_bid_ratio: Optional[float] = Field(default=None, description="실제 낙찰가율(감정가 대비 %)")
    bidders_count: Optional[int] = Field(default=None, description="실제 응찰자 수")


class WinningBidRecord(BaseModel):
    """과거 및 실시간 추적된 낙찰 결과 히스토리 (입찰가 추천 학습/통계용)"""
    id: Optional[int] = None
    case_no: str
    court_name: str
    property_type: str
    region_name: str
    exclusive_area_m2: float
    building_age_years: int
    is_redev_zone: bool
    has_tenant: bool
    occupant_type: str
    has_rights_defect: bool
    unpaid_mgmt_fee: int
    failed_count: int
    appraisal_price: int
    min_bid_price: int
    market_value_at_bid: int
    official_price: int
    winning_bid_price: int
    winning_bid_ratio_appraisal: float  # 감정가 대비 낙찰가율(%)
    winning_bid_ratio_market: float     # 실거래 시세 대비 낙찰가율(%)
    bidders_count: int
    sold_date: str

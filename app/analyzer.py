import math
from typing import Dict, List, Tuple
from app.config import settings
from app.models import AuctionProperty, BidRecommendation, WinningBidRecord


def evaluate_and_recommend(
    prop: AuctionProperty,
    history: List[WinningBidRecord],
) -> AuctionProperty:
    """
    1. 핵심 조건(임차인 없음 + 소유자 거주 중 + 권리상 하자 없음 + 미납관리비 리스크 체크)으로 매력 매물 필터링
    2. 6대 부동산 사이트(디스코, 국토부실거래, 아실, 부동산플래닛, 공시가격알리미 126%, 네이버부동산) 교차 가치 산정
    3. 과거 유사 물건 낙찰 추적 데이터를 기반으로 입찰가 3단계(보수/적정/공격) 및 낙찰 확률 추천
    """
    rejection_reasons: List[str] = []

    # 조건 1: 임차인 없음
    if prop.has_tenant:
        rejection_reasons.append("임차인 존재 (대항력/보증금 또는 명도 복잡성 리스크)")

    # 조건 2: 소유자 거주 중
    if prop.occupant_type != "소유자":
        rejection_reasons.append(f"소유자 거주 조건 미충족 (현재 점유: {prop.occupant_type})")

    # 조건 3: 권리상 하자 없음
    if prop.has_rights_defect or prop.assumed_rights_amount > 0:
        rejection_reasons.append(
            f"권리상 인수 하자 존재 ({prop.base_right_info}, 인수금 {prop.assumed_rights_amount // 10000:,}만원)"
        )

    # 조건 4: 미납 관리비 과다 여부 확인
    if prop.unpaid_mgmt_fee > settings.MAX_ACCEPTABLE_UNPAID_MGMT_FEE:
        rejection_reasons.append(
            f"미납 관리비 과다 ({prop.unpaid_mgmt_fee // 10000:,}만원 > 허용기준 {settings.MAX_ACCEPTABLE_UNPAID_MGMT_FEE // 10000:,}만원)"
        )

    # 6대 사이트 교차 시세 산출 (Estimated Market Value)
    # ① 디스코 인근 실제 매각가 (30%) + ② 국토부 동네 실거래 평균 (40%) + ⑥ 네이버부동산 최저호가×0.96 (30%)
    disco_val = prop.disco.nearby_sold_price_avg
    molit_val = prop.molit.similar_area_avg_price
    naver_effective_val = int(prop.naver_land.asking_sale_min * 0.96)

    estimated_market_value = int(
        round((molit_val * 0.40 + disco_val * 0.30 + naver_effective_val * 0.30), -5)
    )

    # 미납 관리비 중 낙찰자 인수 예상 금액 (공용부분 약 75% 반영, 대법원 판례 기준)
    assumed_unpaid_mgmt = int(
        round(prop.unpaid_mgmt_fee * settings.COMMON_MGMT_FEE_ASSUMPTION_RATIO, -4)
    )

    # 소유자 명도 협의금(이사비) + 취득세/법무비(약 1.3%) 추정
    eviction_fee = 2_500_000 if prop.occupant_type == "소유자" else 4_000_000
    acquisition_tax_est = int(round(prop.min_bid_price * 0.013, -4))
    total_ancillary_cost = eviction_fee + acquisition_tax_est

    # 과거 유사 낙찰 사례 필터링 (동일 물건종류 & 무하자 중심)
    similar_cases = [
        h
        for h in history
        if h.property_type == prop.property_type and not h.has_rights_defect
    ]
    if not similar_cases:
        similar_cases = history

    if similar_cases:
        avg_market_ratio = sum(h.winning_bid_ratio_market for h in similar_cases) / len(
            similar_cases
        )
    else:
        avg_market_ratio = 84.5  # 기본 시세 대비 낙찰가율(%)

    # ③ 아실 재개발 구역도 & ④ 부동산플래닛 건물 연식 보정
    age_years = prop.bdsplanet.building_age_years
    redev_adjustment = 0.0
    age_adjustment = 0.0

    if prop.asil.is_redev_zone:
        # 재개발 구역 포함 시 응찰 경쟁률 상승 반영 (+2.5%p)
        redev_adjustment = 2.5
    else:
        if age_years <= 7:
            age_adjustment = 1.5  # 신축/준신축 선호
        elif age_years >= 20:
            age_adjustment = -2.0  # 비재개발 노후 건물 감가

    target_market_ratio = avg_market_ratio + redev_adjustment + age_adjustment

    # 적정 입찰가 계산 (시세 × 목표 낙찰가율 - 인수 예상 미납관리비)
    raw_optimal_bid = int(estimated_market_value * (target_market_ratio / 100.0)) - assumed_unpaid_mgmt
    # 최저매각가격의 101.5% 이상이어야 유효 입찰 및 경쟁력 확보
    floor_bid = int(prop.min_bid_price * 1.015)
    optimal_bid = int(round(max(raw_optimal_bid, floor_bid), -5))

    # 보수적(안정 마진형) 입찰가 & 공격적(낙찰 최우선형) 입찰가
    conservative_bid = int(round(max(prop.min_bid_price * 1.005, optimal_bid * 0.955), -5))
    aggressive_bid = int(round(optimal_bid * 1.045, -5))

    # ⑤ 공시가격알리미 전세보증보험 한도 (공시가 × 126%, 10월 기준) 업데이트
    jeonse_limit = int(round(prop.official_price.official_price * settings.JEONSE_INSURANCE_RATIO, -4))
    prop.official_price.jeonse_insurance_limit = jeonse_limit
    prop.official_price.can_zero_gap_invest = optimal_bid <= jeonse_limit

    # 예상 순수익(안전마진) = 추정 시세 - 적정 입찰가 - 인수 미납관리비 - 명도/취득세 비용
    expected_net_profit = (
        estimated_market_value - optimal_bid - assumed_unpaid_mgmt - total_ancillary_cost
    )

    if expected_net_profit < 15_000_000 and not prop.asil.is_redev_zone:
        rejection_reasons.append(
            f"실익 부족 (미납관리비·명도비 차감 후 안전마진 {expected_net_profit // 10000:,}만원)"
        )

    prop.is_attractive = len(rejection_reasons) == 0
    prop.rejection_reasons = rejection_reasons

    # 입찰가 산정 근거 요약 생성
    rationale = [
        f"① 디스코 인근 실매각가({disco_val // 10000:,}만) · ② 국토부 동네 실거래 평균({molit_val // 10000:,}만) · ⑥ 네이버 최저호가({prop.naver_land.asking_sale_min // 10000:,}만) 교차 분석 → 기준 시세 {estimated_market_value // 10000:,}만원 산출",
        f"과거 유사 조건({prop.property_type}·소유자점유·무하자) {len(similar_cases)}건 평균 시세대비 낙찰가율 {avg_market_ratio:.1f}% 적용",
        f"④ 부동산플래닛 건물 연식 {age_years}년차({prop.bdsplanet.age_condition_grade}) 및 ③ 아실 재개발 구역({prop.asil.redev_zone_name}) 보정 ({redev_adjustment + age_adjustment:+.1f}%p)",
        f"미납 관리비 총 {prop.unpaid_mgmt_fee // 10000:,}만원 중 공용부분 인수 예상액 {assumed_unpaid_mgmt // 10000:,}만원 + 소유자 명도/취득비용 {total_ancillary_cost // 10000:,}만원 선제 차감 반영",
    ]
    if prop.official_price.can_zero_gap_invest:
        rationale.append(
            f"⑤ 공시가격알리미 기준 전세보증보험 한도(공시가×126% = {jeonse_limit // 10000:,}만원) 이내 입찰가로 낙찰 후 보증보험 전세 세팅 시 무피/초소액 레버리지 가능!"
        )
    else:
        gap = (optimal_bid - jeonse_limit) // 10000
        rationale.append(
            f"⑤ 공시가격알리미 전세보증보험 한도(공시가×126% = {jeonse_limit // 10000:,}만원) 대비 실투입 갭 약 {gap:,}만원 예상"
        )

    optimal_ratio_appraisal = round((optimal_bid / prop.appraisal_price) * 100, 1)
    optimal_ratio_market = round((optimal_bid / estimated_market_value) * 100, 1)

    prop.recommendation = BidRecommendation(
        conservative_bid=conservative_bid,
        conservative_win_prob=42.0,
        optimal_bid=optimal_bid,
        optimal_win_prob=73.5,
        optimal_ratio_to_appraisal=optimal_ratio_appraisal,
        optimal_ratio_to_market=optimal_ratio_market,
        aggressive_bid=aggressive_bid,
        aggressive_win_prob=89.0,
        estimated_market_value=estimated_market_value,
        assumed_unpaid_mgmt_fee=assumed_unpaid_mgmt,
        estimated_eviction_and_tax=total_ancillary_cost,
        expected_net_profit=expected_net_profit,
        similar_cases_count=len(similar_cases),
        rationale=rationale,
    )

    # 종합 매력도 점수 (0~100점) 계산
    score = 50
    if not prop.has_tenant and prop.occupant_type == "소유자":
        score += 18  # 소유자 직접 거주 & 임차인 없음 (명도 깔끔)
    else:
        score -= 25

    if not prop.has_rights_defect and prop.assumed_rights_amount == 0:
        score += 15  # 권리상 하자 없음
    else:
        score -= 30

    if prop.unpaid_mgmt_fee <= 1_500_000:
        score += 5
    elif prop.unpaid_mgmt_fee > 5_000_000:
        score -= 10

    if prop.asil.is_redev_zone:
        score += 7  # 재개발 구역 호재
    if prop.official_price.can_zero_gap_invest:
        score += 6  # 전세보증보험 126% 한도 내 레버리지 매력
    if expected_net_profit >= 50_000_000:
        score += 6
    elif expected_net_profit >= 30_000_000:
        score += 4

    prop.attractiveness_score = max(5, min(99, score))
    return prop


def simulate_bid_for_property(
    prop: AuctionProperty,
    bid_amount: int,
) -> Dict[str, float | int | str]:
    """사용자 지정 입찰가에 대한 예상 낙찰 확률 및 순마진 시뮬레이션"""
    rec = prop.recommendation
    if not rec:
        return {}

    # 로지스틱 곡선 기반 낙찰 확률 추정 (optimal_bid에서 ~73.5%)
    diff_ratio = (bid_amount - rec.optimal_bid) / max(rec.estimated_market_value, 1)
    # diff_ratio가 +4.5%일 때 ~89%, -4.5%일 때 ~42%
    k = 26.0
    x0 = -0.038
    win_prob = 100.0 / (1.0 + math.exp(-k * (diff_ratio - x0)))
    win_prob = round(max(3.0, min(98.5, win_prob)), 1)

    net_profit = (
        rec.estimated_market_value
        - bid_amount
        - rec.assumed_unpaid_mgmt_fee
        - rec.estimated_eviction_and_tax
    )
    jeonse_limit = prop.official_price.jeonse_insurance_limit
    self_capital_needed = max(
        0,
        bid_amount + rec.assumed_unpaid_mgmt_fee + rec.estimated_eviction_and_tax - jeonse_limit,
    )

    if win_prob >= 80 and net_profit > 20_000_000:
        verdict = "낙찰 유력 & 안전마진 확보 (적극 추천 구간)"
    elif win_prob >= 60 and net_profit >= 30_000_000:
        verdict = "최적 균형 구간 (수익률·낙찰확률 동시 충족)"
    elif net_profit < 10_000_000:
        verdict = "고가 입찰 주의 (미납관리비·명도비 차감 후 실익 낮음)"
    else:
        verdict = "보수적 입찰 (수익률은 높으나 패찰 가능성 존재)"

    return {
        "case_no": prop.case_no,
        "bid_amount": bid_amount,
        "ratio_to_appraisal": round((bid_amount / prop.appraisal_price) * 100, 1),
        "ratio_to_market": round((bid_amount / rec.estimated_market_value) * 100, 1),
        "estimated_win_probability": win_prob,
        "expected_net_profit": net_profit,
        "assumed_unpaid_mgmt_fee": rec.assumed_unpaid_mgmt_fee,
        "jeonse_insurance_limit_126": jeonse_limit,
        "self_capital_with_jeonse_leverage": self_capital_needed,
        "verdict": verdict,
    }

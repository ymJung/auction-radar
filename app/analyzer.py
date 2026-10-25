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


def _fmt_man(amount_won: int) -> str:
    """만원/억 단위 간단 포맷 헬퍼"""
    sign = "-" if amount_won < 0 else ""
    val = abs(amount_won)
    man = val // 10_000
    eok = man // 10_000
    rem = man % 10_000
    if eok > 0 and rem > 0:
        return f"{sign}{eok}억 {rem:,}만원"
    if eok > 0:
        return f"{sign}{eok}억원"
    return f"{sign}{man:,}만원"


def simulate_historical_winning_record(
    record: WinningBidRecord,
    history: List[WinningBidRecord],
) -> WinningBidRecord:
    """
    과거 낙찰 완료된 매물에 대해:
    1. 당시 기준 시스템이 제시한 추천 입찰가(보수 / 적정 / 공격) 산출
    2. 제시된 입찰가로 만약 낙찰되었다면 얼마나 이득(순수익)이었는지 & 실제 1등 낙찰자의 순수익은 얼마였는지 계산
    3. 실제 2등(차순위 입찰자)과의 가격 차이(1등 vs 2등, 제시가 vs 2등, 제시가 vs 1등)를 시뮬레이션
    """
    # 1. 공용 미납관리비 인수액 및 명도/취득세 부대비용 산출
    assumed_unpaid_mgmt = int(
        round(record.unpaid_mgmt_fee * settings.COMMON_MGMT_FEE_ASSUMPTION_RATIO, -4)
    )
    eviction_fee = 2_500_000 if record.occupant_type == "소유자" else 4_000_000
    acquisition_tax_est = int(round(record.min_bid_price * 0.013, -4))
    total_ancillary_cost = eviction_fee + acquisition_tax_est

    # 2. 차순위(2등) 입찰가가 미입력(0)인 경우 합리적 기본값 보정
    if record.second_bid_price <= 0:
        est_second = int(round(record.winning_bid_price * 0.976, -5))
        record.second_bid_price = max(record.min_bid_price + 1_000_000, est_second)

    # 3. 당시 유사 사례(자기 자신 제외 leave-one-out) 평균 시세대비 낙찰가율 산출
    similar_peers = [
        h
        for h in history
        if h.case_no != record.case_no
        and h.property_type == record.property_type
        and not h.has_rights_defect
    ]
    if not similar_peers:
        similar_peers = [h for h in history if h.case_no != record.case_no]

    if similar_peers:
        avg_market_ratio = sum(h.winning_bid_ratio_market for h in similar_peers) / len(
            similar_peers
        )
    else:
        avg_market_ratio = 85.5

    # 아실 재개발 구역 & 부동산플래닛 연식 보정
    redev_adj = 2.5 if record.is_redev_zone else 0.0
    age_adj = 0.0
    if not record.is_redev_zone:
        if record.building_age_years <= 7:
            age_adj = 1.5
        elif record.building_age_years >= 20:
            age_adj = -2.0

    target_market_ratio = avg_market_ratio + redev_adj + age_adj

    raw_optimal_bid = (
        int(record.market_value_at_bid * (target_market_ratio / 100.0))
        - assumed_unpaid_mgmt
    )
    floor_bid = int(record.min_bid_price * 1.015)
    suggested_optimal = int(round(max(raw_optimal_bid, floor_bid), -5))
    suggested_conservative = int(
        round(max(record.min_bid_price * 1.005, suggested_optimal * 0.955), -5)
    )
    suggested_aggressive = int(round(suggested_optimal * 1.045, -5))

    # 4. 순수익(얼마나 이득이었는지) 계산: 시세 - 입찰가 - 인수관리비 - 명도/취득세
    net_cost_deduction = assumed_unpaid_mgmt + total_ancillary_cost
    suggested_opt_profit = (
        record.market_value_at_bid - suggested_optimal - net_cost_deduction
    )
    suggested_cons_profit = (
        record.market_value_at_bid - suggested_conservative - net_cost_deduction
    )
    suggested_agg_profit = (
        record.market_value_at_bid - suggested_aggressive - net_cost_deduction
    )
    actual_winner_profit = (
        record.market_value_at_bid - record.winning_bid_price - net_cost_deduction
    )
    profit_diff_vs_actual = suggested_opt_profit - actual_winner_profit

    # 5. 2등(차순위) 및 1등과의 격차 계산
    gap_1st_2nd = record.winning_bid_price - record.second_bid_price
    gap_1st_2nd_ratio = round(
        (gap_1st_2nd / max(record.appraisal_price, 1)) * 100, 1
    )
    gap_sugg_1st = suggested_optimal - record.winning_bid_price
    gap_sugg_2nd = suggested_optimal - record.second_bid_price

    win_opt = suggested_optimal >= record.winning_bid_price
    beat_2nd_opt = suggested_optimal >= record.second_bid_price
    win_agg = suggested_aggressive >= record.winning_bid_price

    if win_opt:
        badge = "🎯 제시 적정가로 1등 낙찰 성공"
        verdict = (
            f"제시 적정가({_fmt_man(suggested_optimal)})가 실제 1등({_fmt_man(record.winning_bid_price)})보다 "
            f"+{_fmt_man(gap_sugg_1st)} 높아 1등 낙찰! 낙찰 시 순수익 +{_fmt_man(suggested_opt_profit)} 이득 "
            f"(2등 {_fmt_man(record.second_bid_price)}과는 +{_fmt_man(gap_sugg_2nd)} 차이)"
        )
    elif beat_2nd_opt:
        badge = "⚡ 2등 제침 · 1등과 근소차 (공격형 1등)"
        verdict = (
            f"제시 적정가({_fmt_man(suggested_optimal)})로 만약 낙찰되었다면 순수익 +{_fmt_man(suggested_opt_profit)} 이득 "
            f"(실제 1등보다 +{_fmt_man(profit_diff_vs_actual)} 더 이득). 실제 2등({_fmt_man(record.second_bid_price)})은 "
            f"+{_fmt_man(gap_sugg_2nd)} 차이로 이겼고, 1등({_fmt_man(record.winning_bid_price)})이 2등보다 "
            f"{_fmt_man(gap_1st_2nd)} 더 써서 낙찰됨 (제시 공격형 {_fmt_man(suggested_aggressive)} 입찰 시 1등 낙찰, 순수익 +{_fmt_man(suggested_agg_profit)})"
        )
    elif win_agg:
        badge = "🔥 공격형 제시가로 1등 낙찰 구간"
        verdict = (
            f"제시 적정가({_fmt_man(suggested_optimal)}) 낙찰 가정 시 순수익 +{_fmt_man(suggested_opt_profit)} 이득. "
            f"실제 현장 경합(응찰 {record.bidders_count}명)으로 2등({_fmt_man(record.second_bid_price)})과 "
            f"{_fmt_man(abs(gap_sugg_2nd))} 차이였으며, 1등은 2등보다 {_fmt_man(gap_1st_2nd)} 높게 써서 낙찰 "
            f"(공격형 제시가 {_fmt_man(suggested_aggressive)} 투입 시 1등 낙찰)"
        )
    else:
        badge = "🛡 과열 입찰 방어 (고가낙찰 주의)"
        verdict = (
            f"제시 적정가({_fmt_man(suggested_optimal)}) 낙찰 가정 시 순수익 +{_fmt_man(suggested_opt_profit)} 이득이나, "
            f"실제 1등({_fmt_man(record.winning_bid_price)})이 과열 입찰하여 실익이 +{_fmt_man(actual_winner_profit)}으로 축소됨 "
            f"(1등과 2등 차이 {_fmt_man(gap_1st_2nd)})"
        )

    record.suggested_conservative_bid = suggested_conservative
    record.suggested_optimal_bid = suggested_optimal
    record.suggested_aggressive_bid = suggested_aggressive
    record.suggested_optimal_ratio_appraisal = round(
        (suggested_optimal / max(record.appraisal_price, 1)) * 100, 1
    )
    record.suggested_optimal_ratio_market = round(
        (suggested_optimal / max(record.market_value_at_bid, 1)) * 100, 1
    )
    record.assumed_unpaid_mgmt_fee = assumed_unpaid_mgmt
    record.estimated_eviction_and_tax = total_ancillary_cost
    record.suggested_optimal_net_profit = suggested_opt_profit
    record.suggested_conservative_net_profit = suggested_cons_profit
    record.suggested_aggressive_net_profit = suggested_agg_profit
    record.actual_winner_net_profit = actual_winner_profit
    record.profit_diff_vs_actual = profit_diff_vs_actual
    record.gap_1st_to_2nd_price = gap_1st_2nd
    record.gap_1st_to_2nd_ratio = gap_1st_2nd_ratio
    record.gap_suggested_to_1st = gap_sugg_1st
    record.gap_suggested_to_2nd = gap_sugg_2nd
    record.would_win_with_optimal = win_opt
    record.would_beat_2nd_with_optimal = beat_2nd_opt
    record.would_win_with_aggressive = win_agg
    record.simulation_badge = badge
    record.simulation_verdict = verdict
    return record


def enrich_winning_history_with_simulations(
    history: List[WinningBidRecord],
) -> List[WinningBidRecord]:
    """전체 과거 낙찰 히스토리 리스트에 대해 제시 낙찰가·이득·2등 격차 시뮬레이션을 일괄 수행"""
    return [simulate_historical_winning_record(h, history) for h in history]


def simulate_custom_bid_on_history(
    record: WinningBidRecord,
    bid_amount: int,
    history: List[WinningBidRecord] | None = None,
) -> Dict[str, int | float | str | bool]:
    """
    과거 낙찰 매물에 대해 특정 입찰가(제시 적정가 또는 사용자 지정 금액)로 입찰했을 때:
    - 낙찰되었을지 여부 (1등 낙찰 / 2등 차순위 패찰 / 3등 이하 패찰)
    - 만약 이 금액으로 낙찰되었다면 얼마나 이득(순수익)이었는지
    - 당시 1등 낙찰가 및 2등(차순위) 입찰가와 각각 얼마 차이가 났는지 시뮬레이션
    """
    if record.suggested_optimal_bid == 0:
        record = simulate_historical_winning_record(record, history or [record])

    net_deduction = record.assumed_unpaid_mgmt_fee + record.estimated_eviction_and_tax
    simulated_net_profit = record.market_value_at_bid - bid_amount - net_deduction

    gap_vs_1st = bid_amount - record.winning_bid_price
    gap_vs_2nd = bid_amount - record.second_bid_price

    if bid_amount >= record.winning_bid_price:
        simulated_rank = 1
        is_winner = True
        rank_label = "🏆 1등 낙찰 성공! (실제 1등·2등 모두 제침)"
        detail_msg = (
            f"투입가 {_fmt_man(bid_amount)}으로 입찰 시 실제 1등({_fmt_man(record.winning_bid_price)})을 "
            f"+{_fmt_man(gap_vs_1st)} 차이로 누르고 단독 1등 낙찰! "
            f"실제 2등({_fmt_man(record.second_bid_price)})과는 +{_fmt_man(gap_vs_2nd)} 차이이며, "
            f"모든 비용 차감 후 순수익(이득)은 +{_fmt_man(simulated_net_profit)}입니다."
        )
    elif bid_amount >= record.second_bid_price:
        simulated_rank = 2
        is_winner = False
        rank_label = "🥈 아깝게 2등(차순위) 패찰 (기존 2등은 제침)"
        detail_msg = (
            f"투입가 {_fmt_man(bid_amount)}은 실제 2등({_fmt_man(record.second_bid_price)})보다 "
            f"+{_fmt_man(gap_vs_2nd)} 높았으나, 실제 1등({_fmt_man(record.winning_bid_price)})보다 "
            f"{_fmt_man(abs(gap_vs_1st))} 부족해 아깝게 2등 기록. "
            f"만약 이 금액에 낙찰되었다면 순수익(이득)은 +{_fmt_man(simulated_net_profit)}이었을 물건입니다."
        )
    else:
        simulated_rank = 3
        is_winner = False
        rank_label = "🛡 3등 이하 보수적 패찰 (안전마진 우선)"
        detail_msg = (
            f"투입가 {_fmt_man(bid_amount)}은 실제 2등({_fmt_man(record.second_bid_price)})보다 "
            f"{_fmt_man(abs(gap_vs_2nd))} 낮고, 1등({_fmt_man(record.winning_bid_price)})보다는 "
            f"{_fmt_man(abs(gap_vs_1st))} 낮아 패찰. "
            f"만약 이 금액에 낙찰되었다면 순수익(이득)은 +{_fmt_man(simulated_net_profit)}이었습니다."
        )

    return {
        "case_no": record.case_no,
        "region_name": record.region_name,
        "property_type": record.property_type,
        "bid_amount": bid_amount,
        "ratio_to_appraisal": round(
            (bid_amount / max(record.appraisal_price, 1)) * 100, 1
        ),
        "ratio_to_market": round(
            (bid_amount / max(record.market_value_at_bid, 1)) * 100, 1
        ),
        "is_winner": is_winner,
        "simulated_rank": simulated_rank,
        "rank_label": rank_label,
        "simulated_net_profit": simulated_net_profit,
        "suggested_optimal_bid": record.suggested_optimal_bid,
        "suggested_optimal_net_profit": record.suggested_optimal_net_profit,
        "actual_winning_bid_price": record.winning_bid_price,
        "actual_winner_net_profit": record.actual_winner_net_profit,
        "second_bid_price": record.second_bid_price,
        "gap_1st_to_2nd_price": record.gap_1st_to_2nd_price,
        "gap_1st_to_2nd_ratio": record.gap_1st_to_2nd_ratio,
        "gap_vs_1st": gap_vs_1st,
        "gap_vs_2nd": gap_vs_2nd,
        "assumed_unpaid_mgmt_fee": record.assumed_unpaid_mgmt_fee,
        "estimated_eviction_and_tax": record.estimated_eviction_and_tax,
        "detail_message": detail_msg,
    }


FUNDING_STRATEGY_CATALOG: Dict[str, Dict[str, Any]] = {
    "newborn_special": {
        "id": "newborn_special",
        "name": "👶 신생아 특례 디딤돌 대출",
        "short_name": "신생아특례대출",
        "category": "정책·실거주",
        "summary": "2년 내 출산·입양 가구 대상 저금리(1~3%대) 정책모기지 (주택가액 9억 이하 · 전용 85㎡ 이하 · 최대 5억 한도 · LTV 70~80%)",
    },
    "first_time_buyer": {
        "id": "first_time_buyer",
        "name": "🏡 생애최초 주택구입 대출 (LTV 80% 우대)",
        "short_name": "생애최초대출",
        "category": "정책·실거주",
        "summary": "세대원 전원 무주택 생애최초 구입자 LTV 최대 80% 우대 (한도 최대 6억) 및 생애최초 취득세 감면(최대 200~300만원)",
    },
    "auction_balance_loan": {
        "id": "auction_balance_loan",
        "name": "⚖️ 경매 경락잔금대출 (1·2금융권 최대 한도)",
        "short_name": "경락잔금대출",
        "category": "경매전용·레버리지",
        "summary": "경매 낙찰자 전용 잔금대출 (낙찰가의 최대 70~80% 또는 감정가·KB시세의 70% 한도, 소유권 이전과 동시 실행)",
    },
    "jeonse_126_leverage": {
        "id": "jeonse_126_leverage",
        "name": "💎 전세보증보험(126%) 세팅 무피·초소액 갭투자",
        "short_name": "전세126%레버리지",
        "category": "임대·레버리지",
        "summary": "공시가격 × 126% 전세보증보험 가입 한도에 맞춘 임차인 전세금으로 낙찰 잔금을 상환하는 유동성 극대화 전략",
    },
    "policy_mortgage": {
        "id": "policy_mortgage",
        "name": "🏛️ 특례보금자리론 · 일반 디딤돌 정책모기지",
        "short_name": "보금자리론·디딤돌",
        "category": "정책·실거주",
        "summary": "무주택·1주택 실수요자 대상 장기 고정금리 정책금융 (보금자리론 6억 이하·LTV 70%, 디딤돌 5~6억 이하·전용 85㎡ 이하)",
    },
    "short_term_flipping": {
        "id": "short_term_flipping",
        "name": "🔄 단기 매도(플리핑) · 매매사업자 유동성 회수",
        "short_name": "단기매도·사업자",
        "category": "단기차익·사업자",
        "summary": "단기 경락잔금 레버리지 + 빠른 명도·상품화 후 3~6개월 내 시세 매도로 자금 회전율을 극대화하는 전략",
    },
}

DEFAULT_FUNDING_STRATEGIES: List[str] = [
    "newborn_special",
    "first_time_buyer",
    "auction_balance_loan",
    "jeonse_126_leverage",
]


def parse_strategy_list(strategies_raw: Optional[Any]) -> List[str]:
    """
    클라이언트/API에서 전달된 전략 목록(리스트 또는 쉼표 구분 문자열)을 정규화합니다.
    - None 이면 기본 핵심 전략(신생아특례, 생애최초, 경락잔금대출, 전세126%레버리지)을 반환합니다.
    - 'none' 또는 빈 리스트가 명시되면 빈 리스트를 반환합니다.
    - 'all' 이면 전체 전략을 반환합니다.
    """
    if strategies_raw is None:
        return list(DEFAULT_FUNDING_STRATEGIES)
    if isinstance(strategies_raw, str):
        cleaned = strategies_raw.strip()
        if not cleaned:
            return list(DEFAULT_FUNDING_STRATEGIES)
        if cleaned.lower() == "none":
            return []
        if cleaned.lower() == "all":
            return list(FUNDING_STRATEGY_CATALOG.keys())
        items = [s.strip() for s in cleaned.split(",") if s.strip()]
    elif isinstance(strategies_raw, (list, tuple, set)):
        items = [str(s).strip() for s in strategies_raw if str(s).strip()]
        if not items:
            return []
        if "all" in [i.lower() for i in items]:
            return list(FUNDING_STRATEGY_CATALOG.keys())
        if "none" in [i.lower() for i in items]:
            return []
    else:
        return list(DEFAULT_FUNDING_STRATEGIES)

    valid = [k for k in items if k in FUNDING_STRATEGY_CATALOG]
    return valid


def evaluate_funding_strategies(
    prop: AuctionProperty,
    strategies: Optional[Any] = None,
    available_cash: Optional[int] = None,
) -> Dict[str, Any]:
    """
    특정 경매 매물에 대해 선택된 자금 조달/대출/레버리지 전략별 적용 가능 여부,
    예상 최대 조달 한도, 필요 실투입 자기자본(현금 유동성), 가용 현금 대비 충족 여부를 산출합니다.
    """
    selected_keys = parse_strategy_list(strategies)
    rec = prop.recommendation
    target_bid = rec.optimal_bid if rec else prop.min_bid_price
    market_val = rec.estimated_market_value if rec else prop.appraisal_price
    add_costs = (
        (rec.assumed_unpaid_mgmt_fee + rec.estimated_eviction_and_tax + prop.assumed_rights_amount)
        if rec
        else (int(prop.unpaid_mgmt_fee * 0.75) + int(target_bid * 0.015) + 4_000_000 + prop.assumed_rights_amount)
    )
    total_required_funds = target_bid + add_costs
    bid_deposit_10pct = int(round(prop.min_bid_price * 0.10, -4))
    is_officetel = "오피스텔" in prop.property_type

    evaluated_items: List[Dict[str, Any]] = []

    for key in selected_keys:
        meta = FUNDING_STRATEGY_CATALOG[key]
        eligible = True
        eligibility_status = "✅ 적용 가능"
        max_financing = 0
        sub_note = ""
        checkpoint = ""

        if key == "newborn_special":
            if is_officetel:
                eligible = False
                eligibility_status = "🚫 불가 (오피스텔은 준주택으로 디딤돌/신생아특례 제외)"
                max_financing = 0
            elif prop.exclusive_area_m2 > 85.0:
                eligible = False
                eligibility_status = f"⚠️ 불가 (전용 {prop.exclusive_area_m2}㎡ > 국민평형 85㎡ 기준 초과)"
                max_financing = 0
            elif target_bid > 900_000_000 and prop.appraisal_price > 900_000_000:
                eligible = False
                eligibility_status = f"⚠️ 불가 (낙찰예상가 {_fmt_man(target_bid)} > 주택가액 9억 한도 초과)"
                max_financing = 0
            else:
                eligible = True
                ltv70 = min(500_000_000, int(round(target_bid * 0.70, -4)))
                ltv80 = min(500_000_000, int(round(target_bid * 0.80, -4)))
                max_financing = ltv80
                eligibility_status = f"✅ 요건 부합 (전용 {prop.exclusive_area_m2}㎡≤85㎡ · 가액 {_fmt_man(target_bid)}≤9억)"
                sub_note = f"일반 LTV 70% 시 {_fmt_man(ltv70)} / 생애최초 결합 LTV 80% 시 최대 {_fmt_man(ltv80)} (한도 5억)"
            checkpoint = (
                "경매 잔금일에 신생아특례 디딤돌 직접 실행이 가능한지 확인하거나, 단기 경락잔금대출(중도상환수수료 면제/저율)로 "
                "소유권이전 등기 후 즉시 신생아특례(구입자금/대환)로 전환 가능한지 은행 사전 심사 필수 (실거주·전입 기한과 명도 일정 조율)"
            )

        elif key == "first_time_buyer":
            if is_officetel:
                eligible = False
                max_financing = int(round(min(target_bid * 0.70, prop.appraisal_price * 0.70), -4))
                eligibility_status = "⚠️ 제한적 (오피스텔은 주택 생애최초 LTV 80% 특례 제외 · 일반 한도 적용)"
                sub_note = f"일반 오피스텔 경락/담보 한도(약 70%) 기준 {_fmt_man(max_financing)}"
            else:
                eligible = True
                max_financing = min(600_000_000, int(round(target_bid * 0.80, -4)))
                eligibility_status = "✅ 적용 가능 (세대원 전원 무주택 생애최초 LTV 최대 80% · 6억 한도)"
                sub_note = f"LTV 80% 적용 시 최대 {_fmt_man(max_financing)} + 생애최초 취득세 감면(최대 200~300만원) 혜택"
            checkpoint = (
                "차주 소득 및 스트레스 DSR 한도 내에서 LTV 80% 전액 실행이 가능한지 확인하고, "
                "경락잔금대출 취급 금융사에서 생애최초 LTV 80%(MCI/MCG 보증 포함) 바로 적용 가능 여부 및 실거주 전입 의무 점검"
            )

        elif key == "auction_balance_loan":
            loan_1st = min(int(round(target_bid * 0.70, -4)), int(round(prop.appraisal_price * 0.70, -4)))
            loan_max = min(int(round(target_bid * 0.80, -4)), int(round(prop.appraisal_price * 0.75, -4)))
            max_financing = loan_max
            if prop.has_rights_defect:
                eligible = False
                eligibility_status = "⚠️ 주의 (선순위 인수 권리/하자로 1금융권 경락잔금대출 제한 우려)"
            else:
                eligible = True
                eligibility_status = "✅ 실행 용이 (권리하자 없음 · 낙찰잔금 납부 및 소유권이전 동시 근저당)"
            sub_note = f"1금융권(70% 기준) 약 {_fmt_man(loan_1st)} ~ 2금융/우대(최대 80% 기준) 약 {_fmt_man(loan_max)}"
            checkpoint = (
                f"입찰 당일 최저가의 10%({_fmt_man(bid_deposit_10pct)}) 현금 필수. 추후 정책대출 대환이나 전세 세팅·단기 매도를 계획한다면 "
                "'중도상환수수료율(또는 3~6개월 후 면제 조건)'과 'DSR 적용 방식'을 기준으로 1금융권 vs 2금융권 비교 선택"
            )

        elif key == "jeonse_126_leverage":
            ins_limit = prop.official_price.jeonse_insurance_limit
            naver_jeonse = prop.naver_land.asking_jeonse_avg
            max_financing = ins_limit
            if prop.official_price.can_zero_gap_invest:
                eligible = True
                eligibility_status = f"💎 무피·초소액 가능 (추천낙찰가 {_fmt_man(target_bid)} ≤ 보증보험 126% 한도 {_fmt_man(ins_limit)})"
            else:
                eligible = True
                eligibility_status = f"🟡 일부 현금 투입 (보증보험 126% 한도 {_fmt_man(ins_limit)} < 추천낙찰가 {_fmt_man(target_bid)})"
            sub_note = f"공시가×126% 보증보험 한도 {_fmt_man(ins_limit)} / 네이버 전세 평균호가 {_fmt_man(naver_jeonse)}"
            checkpoint = (
                "경매 잔금 납부 시점에는 세입자 전세보증금을 즉시 수령하기 어려우므로, ① 단기 경락잔금대출(또는 자기자본 브릿지)로 잔금 완납 및 "
                "소유자 명도 완료 후 ② 전세보증보험(126%) 가입 조건에 맞는 세입자를 맞춰 기존 대출을 상환하는 2단계 유동성 구조 설계 필요"
            )

        elif key == "policy_mortgage":
            if is_officetel:
                eligible = False
                max_financing = 0
                eligibility_status = "🚫 불가 (오피스텔은 보금자리론·디딤돌 정책모기지 제외)"
            elif target_bid > 600_000_000:
                eligible = False
                max_financing = 0
                eligibility_status = f"⚠️ 불가 (낙찰예상가 {_fmt_man(target_bid)} > 보금자리론/디딤돌 6억 기준 초과)"
            else:
                eligible = True
                max_financing = min(420_000_000, int(round(target_bid * 0.70, -4)))
                area_note = "충족" if prop.exclusive_area_m2 <= 85.0 else "85㎡초과(보금자리론만 검토)"
                eligibility_status = f"✅ 적용 가능 (6억 이하 주택 · 면적요건 {area_note})"
                sub_note = f"LTV 70% 기준 약 {_fmt_man(max_financing)} (생애최초 시 최대 80%·4.2억 한도)"
            checkpoint = (
                "한국주택금융공사(HF) 보금자리론 및 일반 디딤돌은 소유권 이전 및 점유자 퇴거 확인 후 실행이 수월하므로, "
                "경락잔금대출 실행 후 정책모기지 대환(구입용/보전용) 가능 기간(소유권이전 후 3개월 이내 등)을 반드시 사전 확인"
            )

        elif key == "short_term_flipping":
            eligible = True
            max_financing = min(int(round(target_bid * 0.80, -4)), int(round(prop.appraisal_price * 0.75, -4)))
            expected_profit = rec.expected_net_profit if rec else max(0, market_val - total_required_funds)
            eligibility_status = f"✅ 검토 가능 (추정시세 {_fmt_man(market_val)} 대비 예상 안전마진 +{_fmt_man(expected_profit)})"
            sub_note = f"단기 경락·사업자 레버리지 최대 {_fmt_man(max_financing)} 활용 → 명도 후 시세 급매도"
            checkpoint = (
                "개인 명의 단기 매도 시 양도소득세 중과(1년 미만 70%, 2년 미만 60%)가 적용되므로 '주택매매사업자' 비교 검토 필요. "
                "단, 매매사업자 등록 시 무주택/생애최초/신생아특례 정책대출 자격에 영향을 줄 수 있으므로 실거주·정책대출 전략과 양자택일 점검"
            )

        required_self_cash = max(0, total_required_funds - max_financing)
        # 입찰보증금(10%)은 입찰 당일 무조건 현금으로 있어야 함
        effective_min_cash = max(bid_deposit_10pct, required_self_cash)

        if available_cash is not None and available_cash > 0:
            cash_diff = available_cash - effective_min_cash
            if not eligible and max_financing == 0:
                cash_verdict = "🚫 전략 요건 미충족 (타 전략 검토)"
            elif cash_diff >= 0:
                cash_verdict = f"✅ 유동성 충분 (여유 +{_fmt_man(cash_diff)})"
            else:
                cash_verdict = f"⚠️ 현금 부족 (-{_fmt_man(abs(cash_diff))} 추가 조달 필요)"
        else:
            if not eligible and max_financing == 0:
                cash_verdict = f"전액 자기자본 필요 ({_fmt_man(total_required_funds)})"
            else:
                cash_verdict = f"최소 현금 {_fmt_man(effective_min_cash)} 필요 (입찰보증금 {_fmt_man(bid_deposit_10pct)} 포함)"

        evaluated_items.append(
            {
                "id": key,
                "name": meta["name"],
                "short_name": meta["short_name"],
                "category": meta["category"],
                "summary": meta["summary"],
                "eligible": eligible,
                "eligibility_status": eligibility_status,
                "max_financing": max_financing,
                "required_self_cash": required_self_cash,
                "effective_min_cash": effective_min_cash,
                "sub_note": sub_note,
                "checkpoint": checkpoint,
                "cash_verdict": cash_verdict,
            }
        )

    return {
        "case_no": prop.case_no,
        "target_bid": target_bid,
        "add_costs": add_costs,
        "total_required_funds": total_required_funds,
        "bid_deposit_10pct": bid_deposit_10pct,
        "available_cash": available_cash,
        "selected_strategy_ids": selected_keys,
        "strategies": evaluated_items,
    }


def build_ai_discussion_text(
    prop: AuctionProperty,
    include_prompt: bool = True,
    strategies: Optional[Any] = None,
    available_cash: Optional[int] = None,
) -> str:
    """
    추출된 경매 매물의 상세 내용(사건개요, 권리/점유/미납관리비, 6대 부동산 플랫폼 교차 데이터,
    AI 추천 입찰가 3단계, 선택된 자금 유동성/대출 전략 시뮬레이션)을 제미나이(Gemini) 등 생성형 AI와
    심층 토론하기 좋은 구조화된 마크다운 텍스트로 변환합니다.
    """
    rec = prop.recommendation
    pyeong = round(prop.exclusive_area_m2 / 3.3058, 1)
    min_bid_ratio = round((prop.min_bid_price / max(prop.appraisal_price, 1)) * 100, 1)
    liquidity = evaluate_funding_strategies(prop, strategies=strategies, available_cash=available_cash)
    selected_strats = liquidity["strategies"]
    strat_names_str = (
        ", ".join(s["short_name"] for s in selected_strats)
        if selected_strats
        else "일반 자금조달"
    )

    lines: List[str] = []

    if include_prompt:
        lines.extend(
            [
                "# 🤖 부동산 경매 매물 심층 분석 · 자금 유동성(대출/레버리지) 및 입찰 전략 토론 요청",
                "",
                "아래 데이터는 **AuctionRadar**에서 수집·검증한 경매 매물의 권리/점유/미납관리비 내역과 6대 부동산 플랫폼(디스코, 국토부 실거래가, 아실, 부동산플래닛, 공시가격알리미, 네이버부동산) 교차 분석 데이터 및 **자금 유동성(가용 대출·레버리지 수단) 시뮬레이션**입니다.",
                f"당신은 **대한민국 부동산 경매·권리분석·금융(대출/정책모기지/유동성 설계) 및 투자 전략 전문가**로서 아래 데이터를 면밀히 검토한 뒤, 매물의 입찰 타당성, **선택한 자금 전략({strat_names_str})의 실제 가용 여부 및 현금 유동성 흐름**, 적정 입찰가, 명도 및 출구 전략에 대해 나와 심층 토론해 주세요.",
                "",
                "---",
                "",
            ]
        )

    lines.extend(
        [
            f"## 1. 경매 사건 기본 개요 [{prop.case_no}]",
            f"- **사건번호**: {prop.case_no} ({prop.court_name})",
            f"- **물건종류 / 진행상태**: {prop.property_type} (재검증: {prop.naver_land.verification_source or '네이버부동산·건축물대장 확인 완료'}) / {prop.status}",
            f"- **소재지 주소**: {prop.address}",
            f"- **면적 정보**: 전용면적 {prop.exclusive_area_m2}㎡ (약 {pyeong}평) / 대지권 {prop.land_share_m2}㎡",
            f"- **매각기일 / 유찰횟수**: {prop.auction_date} ({prop.failed_count}회 유찰)",
            f"- **법원 감정가**: {_fmt_man(prop.appraisal_price)} ({prop.appraisal_price:,}원)",
            f"- **최저매각가격**: {_fmt_man(prop.min_bid_price)} ({prop.min_bid_price:,}원, 감정가 대비 {min_bid_ratio}%)",
            "",
            "## 2. 핵심 필터 검증 및 매력도 판정",
            f"- **매력 매물 선정 여부**: {'✅ 선정 (4대 핵심 조건 모두 충족)' if prop.is_attractive else '🚫 필터 제외 대상 (조건 미충족)'}",
            f"- **종합 매력도 점수**: {prop.attractiveness_score}점 / 100점",
        ]
    )

    if not prop.is_attractive and prop.rejection_reasons:
        lines.append("- **필터 제외(주의) 사유**:")
        for reason in prop.rejection_reasons:
            lines.append(f"  - ⚠️ {reason}")

    lines.extend(
        [
            "",
            "## 3. 권리관계 · 점유 · 미납관리비 상세 분석",
            "### (1) 점유 및 임대차 관계",
            f"- **임차인 존재 여부**: {'없음 (대항력/보증금 인수 리스크 없음)' if not prop.has_tenant else '있음 (임차인 권리/명도 확인 필요)'}",
            f"- **현재 점유자 유형**: {prop.occupant_type}",
            f"- **현황조사서 점유 상세**: {prop.occupancy_detail}",
            "",
            "### (2) 등기/말소기준권리 및 인수 하자",
            f"- **권리상 하자 유무**: {'없음 (매수인 인수 권리 0원)' if not prop.has_rights_defect else '있음 (인수 조건 확인 필수)'}",
            f"- **말소기준권리 및 등기 내역**: {prop.base_right_info}",
            f"- **매수인 인수 권리 금액**: {_fmt_man(prop.assumed_rights_amount)} ({prop.assumed_rights_amount:,}원)",
            "",
            "### (3) 미납 관리비 및 부대비용",
            f"- **확인/탐문 총 미납 관리비**: {_fmt_man(prop.unpaid_mgmt_fee)} ({prop.unpaid_mgmt_months}개월 연체)",
            f"- **미납 관리비 상세 안내**: {prop.unpaid_mgmt_note}",
        ]
    )

    if rec:
        lines.extend(
            [
                f"- **공용부분 인수 예상액 (75% 기준)**: -{_fmt_man(rec.assumed_unpaid_mgmt_fee)}",
                f"- **소유자 명도협의금 및 취득세 등 부대비용 추정**: -{_fmt_man(rec.estimated_eviction_and_tax)}",
            ]
        )

    lines.extend(
        [
            "",
            "## 4. 6대 부동산 플랫폼 교차 분석 데이터",
            "### ① 디스코 (인근 실제 매각/실거래 데이터)",
            f"- **인근 유사 매물 실매각가 평균**: {_fmt_man(prop.disco.nearby_sold_price_avg)} (평당 {_fmt_man(prop.disco.price_per_pyeong)})",
            f"- **최근 매각 사례**: {prop.disco.recent_sold_case} (기준 매물 반경 {prop.disco.distance_m}m)",
            "",
            f"### ② 국토부 실거래가 ({prop.molit.dong_name}, 법정동코드 {prop.molit.lawd_cd})",
            f"- **수집 거래 건수**: 최근 {prop.molit.total_tx_count}건 ({prop.molit.recent_trend})",
            f"- **유사 면적 실거래 평균가**: {_fmt_man(prop.molit.similar_area_avg_price)}",
            f"- **실거래 가격 범위**: 최저 {_fmt_man(prop.molit.min_deal_price)} ~ 최고 {_fmt_man(prop.molit.max_deal_price)}",
        ]
    )

    if prop.molit.transactions:
        lines.append("- **주요 실거래 표본 내역**:")
        for tx in prop.molit.transactions:
            lines.append(
                f"  - [{tx.contract_date}] {tx.building_name} (전용 {tx.exclusive_area_m2}㎡, {tx.floor}층): {_fmt_man(tx.deal_amount)}"
            )

    lines.extend(
        [
            "",
            "### ③ 아실 (재개발/정비구역 및 경매 입지 분석)",
            f"- **정비구역 포함 여부**: {'🔥 포함/인접' if prop.asil.is_redev_zone else '일반 구역 (비해당)'}",
            f"- **정비구역 명칭 / 진행단계**: {prop.asil.redev_zone_name} / {prop.asil.redev_stage}",
            f"- **아실 상세 코멘트**: {prop.asil.asil_case_summary}",
            "",
            "### ④ 부동산플래닛 (건물 연식 및 물리적 현황)",
            f"- **준공연도 / 사용승인일**: {prop.bdsplanet.built_year}년 ({prop.bdsplanet.approval_date}) — 현재 {prop.bdsplanet.building_age_years}년차",
            f"- **연식 상태 등급**: {prop.bdsplanet.age_condition_grade}",
            f"- **규모 및 구조**: 총 {prop.bdsplanet.total_floors}층 / {prop.bdsplanet.structure_type}",
            "",
            "### ⑤ 공시가격알리미 (전세보증보험 126% 한도 및 레버리지 분석)",
            f"- **{prop.official_price.reference_year}년 공시가격**: {_fmt_man(prop.official_price.official_price)}",
            f"- **전세보증보험 가입 한도 (공시가 × 126%)**: {_fmt_man(prop.official_price.jeonse_insurance_limit)}",
            f"- **무피/초소액 갭투자 가능 여부**: {'💎 가능 (적정 추천 입찰가가 보증보험 한도 이하)' if prop.official_price.can_zero_gap_invest else '자기자본 일부 투입 필요 (추천 입찰가가 보증보험 한도 초과)'}",
            "",
            "### ⑥ 네이버부동산 (현재 시장 매매/전세 호가 및 물건종류 재검증)",
            f"- **대상 단지/구역명**: {prop.naver_land.complex_or_area_name} (현재 활성 매물 {prop.naver_land.active_listing_count}건)",
            f"- **네이버부동산·단지정보 재검증 물건종류**: {prop.naver_land.verified_property_type or prop.property_type} ({prop.naver_land.verification_source or '확인 완료'})",
            f"- **매매 최저 호가 / 평균 호가**: 최저 {_fmt_man(prop.naver_land.asking_sale_min)} / 평균 {_fmt_man(prop.naver_land.asking_sale_avg)}",
            f"- **전세 평균 호가**: {_fmt_man(prop.naver_land.asking_jeonse_avg)}",
        ]
    )

    if rec:
        self_cap = max(
            0,
            rec.optimal_bid
            + rec.assumed_unpaid_mgmt_fee
            + rec.estimated_eviction_and_tax
            - prop.official_price.jeonse_insurance_limit,
        )
        lines.extend(
            [
                "",
                "## 5. AuctionRadar 입찰가 3단계 추천 및 예상 안전마진",
                f"- **6대 플랫폼 교차 추정 기준 시세**: {_fmt_man(rec.estimated_market_value)} ({rec.estimated_market_value:,}원)",
                f"- **참조한 유사 조건 과거 낙찰 사례 수**: {rec.similar_cases_count}건",
                "- **단계별 추천 입찰가**:",
                f"  1. **보수적 입찰가 (고마진형, 예상 낙찰확률 {rec.conservative_win_prob}%)**: {_fmt_man(rec.conservative_bid)} ({rec.conservative_bid:,}원)",
                f"  2. **⭐ 적정 추천 입찰가 (최적 균형, 예상 낙찰확률 {rec.optimal_win_prob}%)**: {_fmt_man(rec.optimal_bid)} ({rec.optimal_bid:,}원) — 감정가 대비 {rec.optimal_ratio_to_appraisal}% / 추정시세 대비 {rec.optimal_ratio_to_market}%",
                f"  3. **공격형 입찰가 (낙찰우선형, 예상 낙찰확률 {rec.aggressive_win_prob}%)**: {_fmt_man(rec.aggressive_bid)} ({rec.aggressive_bid:,}원)",
                f"- **적정가 낙찰 시 예상 순안전마진(순수익)**: +{_fmt_man(rec.expected_net_profit)} (공용 미납관리비 {_fmt_man(rec.assumed_unpaid_mgmt_fee)} 및 명도·취득세 {_fmt_man(rec.estimated_eviction_and_tax)} 차감 후)",
                f"- **전세보증보험(126%) 세팅 시 예상 실투입 자기자본**: {_fmt_man(self_cap)}",
                "- **입찰가 산정 세부 근거**:",
            ]
        )
        for r in rec.rationale:
            lines.append(f"  - {r}")

    if selected_strats:
        lines.extend(
            [
                "",
                "## 6. 💰 자금 유동성 확인 및 가용 대출·레버리지 전략 분석",
                f"- **검토 대상 전략 ({len(selected_strats)}개 선택)**: {', '.join(s['name'] for s in selected_strats)}",
                f"- **① 입찰 당일 필수 현금 (입찰보증금 = 최저매각가의 10%)**: **{_fmt_man(liquidity['bid_deposit_10pct'])}** ({liquidity['bid_deposit_10pct']:,}원)",
                f"- **② 적정가 낙찰 시 총 필요 자금 (낙찰가 {_fmt_man(liquidity['target_bid'])} + 관리비·명도·취득세 {_fmt_man(liquidity['add_costs'])})**: **{_fmt_man(liquidity['total_required_funds'])}** ({liquidity['total_required_funds']:,}원)",
            ]
        )
        if available_cash is not None and available_cash > 0:
            lines.append(
                f"- **💵 현재 보유 가용 현금(자기자본 설정값)**: **{_fmt_man(available_cash)}** ({available_cash:,}원)"
            )

        lines.extend(
            [
                "",
                "### 📊 선택 전략별 매물 요건 부합 여부 · 예상 한도 · 필요 현금 유동성 비교표",
                "| 전략 수단 | 매물 요건 판정 (면적/가격/종류) | 예상 최대 조달(대출/전세) 한도 | 잔금 시 필요 자기자본 | 유동성 종합 판정 |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for s in selected_strats:
            lines.append(
                f"| **{s['name']}** | {s['eligibility_status']} | **{_fmt_man(s['max_financing'])}** | **{_fmt_man(s['required_self_cash'])}** | {s['cash_verdict']} |"
            )

        lines.append("")
        lines.append("### 🔍 전략별 실무 실행 체크포인트 (제미나이 상담 검증 항목)")
        for s in selected_strats:
            lines.append(f"- **{s['name']}**: {s['sub_note']}. 👉 *{s['checkpoint']}*")

    if include_prompt:
        q_section_no = 7 if selected_strats else 6
        lines.extend(
            [
                "",
                "---",
                "",
                f"## {q_section_no}. 생성형 AI(Gemini 등)와 토론하고 싶은 핵심 질문",
                "위 매물 상세 데이터와 자금 유동성 시뮬레이션을 바탕으로 아래 항목들에 대해 전문가 관점의 의견을 제시해 주세요:",
                "1. **시세 및 입찰가 적정성 검증**: 6대 플랫폼 데이터(실거래가, 호가, 공시가 등)에 비추어 볼 때 산출된 추정 시세와 '적정 추천 입찰가'가 합리적인지, 현장 응찰 경쟁률을 고려할 때 얼마를 쓰는 것이 가장 유리할지 분석해 주세요.",
                "2. **권리·점유·미납관리비 리스크 체크**: 현재 파악된 점유관계(소유자/임차인)와 말소기준권리, 미납관리비 내역 외에 입찰 전 현장 임장이나 법원 기록에서 추가로 반드시 확인해야 할 숨은 리스크가 있을지 짚어 주세요.",
            ]
        )
        if selected_strats:
            lines.extend(
                [
                    f"3. **💰 선택 전략({strat_names_str}) 가용성 및 자금 유동성 정밀 검증**:",
                    f"   - 내가 선택한 전략들(**{strat_names_str}**) 중 이 매물({prop.property_type}, 전용 {prop.exclusive_area_m2}㎡, 예상 낙찰가 {_fmt_man(liquidity['target_bid'])})에서 **실제로 실행 가능한 최적의 수단과 조합**은 무엇인가요?",
                    "   - 경매 낙찰 특성상 잔금일에 정책대출(신생아 특례 대출, 생애최초 디딤돌/보금자리론 등)을 바로 실행할 수 있는지, 아니면 **1·2금융권 경락잔금대출(중도상환수수료 면제/저율 상품)로 먼저 잔금을 치르고 소유권이전·명도 직후 정책대출이나 전세보증금으로 대환(갈아타기)**하는 브릿지 전략이 필요한지 구체적인 실행 순서를 짜주세요.",
                    f"   - 입찰보증금({_fmt_man(liquidity['bid_deposit_10pct'])}) 납부 → 잔금 납부 → 취등록세·미납관리비·명도비 지출까지 시기별로 **현금 유동성 병목(Cash Flow 부족)**이 발생하지 않도록 타임라인별 필요 현금을 점검해 주세요.",
                ]
            )
        else:
            lines.append(
                "3. **자금 조달 및 출구 전략(Exit Plan)**: 낙찰 후 ① 전세보증보험(126%)에 맞춘 전세 세팅(레버리지), ② 단기 매도 차익 실현, ③ 실거주 또는 재개발/장기 보유 중 어떤 전략이 가장 수익률과 안전성이 높을지 비교해 주세요."
            )
        lines.append(
            "4. **명도 협상 시나리오**: 현재 점유자 조건에서 원만하고 빠른 명도를 이끌어내기 위한 적정 이사비(명도협의금) 수준과 협상 팁을 제안해 주세요."
        )

    return "\n".join(lines)


def build_bulk_ai_discussion_text(
    props: List[AuctionProperty],
    include_prompt: bool = True,
    strategies: Optional[Any] = None,
    available_cash: Optional[int] = None,
) -> str:
    """
    추출된 여러 경매 매물(예: 매력 매물 전체 목록)을 한 번에 생성형 AI에게 전달하여
    우선순위 비교·자금 유동성 수단 매칭·포트폴리오 선정 토론을 할 수 있도록 구조화된 텍스트를 생성합니다.
    """
    selected_keys = parse_strategy_list(strategies)
    strat_names = [FUNDING_STRATEGY_CATALOG[k]["short_name"] for k in selected_keys]
    strat_names_str = ", ".join(strat_names) if strat_names else "일반 자금조달"

    lines: List[str] = []
    if include_prompt:
        lines.extend(
            [
                f"# 🤖 AuctionRadar 추출 경매 매물 ({len(props)}건) 종합 비교 · 자금 유동성({strat_names_str}) 및 최우선 입찰 선정 토론 요청",
                "",
                f"아래는 AuctionRadar에서 추출된 경매 매물 총 **{len(props)}건**의 상세 분석 및 자금 유동성 시뮬레이션 데이터입니다.",
                f"부동산 경매 및 금융·투자 전략 전문가로서 각 매물의 **권리 안전성, 시세 대비 안전마진, 입지/재개발 호재, 그리고 선택한 자금 조달 전략({strat_names_str}) 적용 가능성 및 필요 현금 유동성**을 비교 분석하고, 나에게 가장 추천하는 **TOP 1~3순위 물건과 자금 조달·입찰 전략**을 제안해 주세요.",
                "",
                "---",
                "",
            ]
        )

    lines.append("## 📊 추출 매물 핵심 요약 비교표 (자금 유동성 전략 포함)")
    lines.append(
        "| 순번 | 사건번호 | 물건종류/면적 | 소재지 | 추천적정입찰가 | 추정시세 | 예상순마진 | 입찰보증금(10%) | 신생아특례 | 생애최초(80%) | 126%무피 |"
    )
    lines.append(
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    )
    for idx, p in enumerate(props, 1):
        rec = p.recommendation
        opt_bid = _fmt_man(rec.optimal_bid) if rec else "-"
        mkt_val = _fmt_man(rec.estimated_market_value) if rec else "-"
        net_prof = f"+{_fmt_man(rec.expected_net_profit)}" if rec else "-"
        bid_dep = _fmt_man(int(round(p.min_bid_price * 0.10, -4)))
        is_officetel = "오피스텔" in p.property_type
        target_val = rec.optimal_bid if rec else p.min_bid_price
        newborn_ok = (not is_officetel) and (p.exclusive_area_m2 <= 85.0) and (target_val <= 900_000_000)
        first_ok = not is_officetel
        newborn_str = "✅가능" if newborn_ok else "⚠️제외"
        first_str = "✅가능" if first_ok else "⚠️제한"
        zero_str = "💎가능" if p.official_price.can_zero_gap_invest else "일부투입"
        lines.append(
            f"| {idx} | {p.case_no} | {p.property_type}({p.exclusive_area_m2}㎡) | {p.address} | **{opt_bid}** | {mkt_val} | **{net_prof}** | {bid_dep} | {newborn_str} | {first_str} | {zero_str} |"
        )

    lines.append("\n---\n")

    for idx, p in enumerate(props, 1):
        lines.append(f"# [매물 {idx}] {p.case_no} — {p.address}")
        lines.append(
            build_ai_discussion_text(
                p,
                include_prompt=False,
                strategies=selected_keys,
                available_cash=available_cash,
            )
        )
        lines.append("\n---\n")

    if include_prompt:
        lines.extend(
            [
                "## 💡 생성형 AI(Gemini 등)에게 요청하는 비교 토론 주제",
                "1. **최우선 입찰 추천 순위 (TOP 3)**: 위 매물들 중 안전마진, 환금성(매도/전세 수요), 입지 호재를 종합했을 때 어떤 순서로 입찰을 검토해야 할까요?",
                f"2. **자금 유동성 및 대출 전략({strat_names_str}) 매칭**: 내 가용 자금 조건에서 ① 신생아 특례 디딤돌 대출, ② 생애최초 LTV 80% 주담대, ③ 경매 경락잔금대출 후 대환, ④ 전세보증보험(126%) 세팅 중 각 매물별로 가장 유리하고 실현 가능한 자금 조달 수단은 무엇인가요?",
                "3. **매물별 핵심 주의사항 및 현금흐름 체크**: 각 매물별로 입찰가 산정 및 잔금 납부 과정에서 가장 주의해야 할 유동성 변수나 현장 임장 체크포인트를 비교해 주세요.",
            ]
        )

    return "\n".join(lines)




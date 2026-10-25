import asyncio
import html
import os
import re
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv

from app.analyzer import (
    build_ai_discussion_text,
    simulate_bid_for_property,
    simulate_custom_bid_on_history,
)
from app.config import HOME_ENV_PATH, settings
from app.database import (
    ensure_seeded,
    get_or_analyze_property_by_case_no,
    load_all_properties,
    load_property_by_case_no,
    load_winning_history,
    load_winning_record_by_case_no,
    save_pipeline_results,
)
from app.models import AuctionProperty, WinningBidRecord
from app.scrapers.parsers import normalize_case_no
from app.scrapers.pipeline import run_scraping_and_analysis_pipeline


def format_eok_man(amount_won: int) -> str:
    """원 단위를 'X억 Y,ZZZ만원' 형태로 가독성 있게 변환"""
    man = amount_won // 10_000
    eok = man // 10_000
    rem_man = man % 10_000
    if eok > 0 and rem_man > 0:
        return f"{eok}억 {rem_man:,}만원"
    if eok > 0:
        return f"{eok}억원"
    return f"{man:,}만원"


def get_bot2_credentials() -> tuple[str, str]:
    if HOME_ENV_PATH.exists():
        load_dotenv(HOME_ENV_PATH, override=True)
    chat_id = os.getenv("TELEGRAM_USER_ID", settings.TELEGRAM_USER_ID).strip()
    bot2_raw = os.getenv("TELEGRAM_BOT_2", settings.TELEGRAM_BOT_2).strip()
    return chat_id, bot2_raw.replace(" ", "")


def build_main_menu_keyboard() -> Dict[str, Any]:
    """텔레그램 인라인 버튼 메인 메뉴"""
    return {
        "inline_keyboard": [
            [
                {"text": "🔎 사건번호 조회 안내 (예: 2025타경 2768)", "callback_data": "menu:lookup_help"},
                {"text": "⚡ 2025타경2768 즉시분석", "callback_data": "prop:2025타경2768"},
            ],
            [
                {"text": "✨ 매력 매물 TOP 목록 (클릭해서 상세)", "callback_data": "menu:attractive"},
            ],
            [
                {"text": "🔥 ③ 아실 재개발 구역 매물", "callback_data": "menu:redev"},
                {"text": "💎 ⑤ 공시가×126% 무피/소액", "callback_data": "menu:zerogap"},
            ],
            [
                {"text": "📊 과거 낙찰(제시가·이득·2등격차) 시뮬", "callback_data": "menu:history"},
                {"text": "🚫 필터 탈락 매물 비교", "callback_data": "menu:rejected"},
            ],
            [
                {"text": "🔄 6대 사이트 즉시 재스크래핑 & 분석", "callback_data": "action:scrape"},
            ],
        ]
    }


def build_persistent_reply_keyboard() -> Dict[str, Any]:
    """채팅창 하단 고정 앱 버튼 (ReplyKeyboardMarkup)"""
    return {
        "keyboard": [
            [{"text": "🔎 사건번호 조회 안내"}, {"text": "2025타경 2768"}, {"text": "✨ 매력 매물 목록"}],
            [{"text": "🔥 재개발 매물"}, {"text": "💎 보증보험 126% 매물"}, {"text": "📊 낙찰가율 추적 DB"}],
            [{"text": "🔄 즉시 재스크래핑"}, {"text": "🏠 메인 메뉴"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_property_list_view(mode: str = "attractive") -> tuple[str, Dict[str, Any]]:
    ensure_seeded()
    all_props = load_all_properties(attractive_only=False)

    if mode == "attractive":
        items = [p for p in all_props if p.is_attractive]
        title = "✨ <b>[매력 매물 목록] 임차인無 · 소유자거주 · 권리무하자 · 관리비검증</b>"
    elif mode == "redev":
        items = [p for p in all_props if p.is_attractive and p.asil.is_redev_zone]
        title = "🔥 <b>[③ 아실 재개발/정비구역 포함 매력 매물]</b>"
    elif mode == "zerogap":
        items = [
            p
            for p in all_props
            if p.is_attractive and p.official_price.can_zero_gap_invest
        ]
        title = "💎 <b>[⑤ 공시가×126% 전세보증보험 한도 내 무피/소액 가능 매물]</b>"
    else:
        items = [p for p in all_props if not p.is_attractive]
        title = "🚫 <b>[필터 탈락 매물 (임차인/권리하자/관리비과다 비교용)]</b>"

    lines = [
        title,
        "아래 버튼을 누르면 <b>6대 사이트 교차분석 · 미납관리비 · 추천 입찰가 시뮬레이터</b>를 바로 볼 수 있습니다.",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    buttons: List[List[Dict[str, str]]] = []

    for idx, p in enumerate(items, 1):
        rec = p.recommendation
        opt_str = format_eok_man(rec.optimal_bid) if rec else "-"
        win_prob = f"{rec.optimal_win_prob:.0f}%" if rec else "-"
        badges = []
        if p.asil.is_redev_zone:
            badges.append("🔥재개발")
        if p.official_price.can_zero_gap_invest:
            badges.append("💎126%무피")
        badge_str = f" [{'/'.join(badges)}]" if badges else ""

        lines.append(
            f"\n<b>{idx}. [{p.case_no}] {p.property_type} ({p.attractiveness_score}점)</b>{badge_str}\n"
            f"📍 {p.address}\n"
            f"💰 최저 {format_eok_man(p.min_bid_price)} → 🎯 <b>추천입찰 {opt_str} (확률 {win_prob})</b>"
        )
        if not p.is_attractive and p.rejection_reasons:
            lines.append(f"⚠️ 제외사유: {p.rejection_reasons[0]}")

        short_addr = " ".join(p.address.split()[1:4])
        buttons.append(
            [
                {
                    "text": f"📌 {idx}번 상세 & 입찰추천 [{p.case_no} {short_addr}]",
                    "callback_data": f"prop:{p.case_no}",
                }
            ]
        )

    buttons.append(
        [
            {"text": "📊 과거 낙찰(제시가·이득·2등격차) 시뮬레이션", "callback_data": "menu:history"},
            {"text": "🏠 메인 메뉴로", "callback_data": "menu:home"},
        ]
    )
    return "\n".join(lines), {"inline_keyboard": buttons}


def build_lookup_help_view() -> tuple[str, Dict[str, Any]]:
    text = "\n".join(
        [
            "🔎 <b>[사건번호 즉시 권리·매력도·적정경매가 분석 안내]</b>",
            "",
            "채팅창에 알고 싶은 <b>사건번호</b>를 그대로 입력하시면,",
            "1️⃣ <b>권리관계 및 점유 분석</b> (말소기준권리, 임차인 대항력/인수 유무, 소유자 거주 여부, 미납관리비 공용분 선제 차감)",
            "2️⃣ <b>얼마나 매력적인지 종합 매력도 점수(0~100점) 및 4대 핵심 필터 통과 여부</b>",
            "3️⃣ <b>6대 부동산 사이트 교차 시세 및 적정 경매 입찰가 (보수/적정/공격 3단계 + 안전마진)</b>",
            "를 즉시 브리핑해 드립니다!",
            "",
            "💡 <b>입력 예시 (채팅창에 바로 입력하거나 아래 버튼 클릭)</b>:",
            " • <code>2025타경 2768</code> (또는 <code>2025타경2768</code>)",
            " • <code>/case 2025타경 2768</code>",
            " • <code>2025타경 2768 103000</code> (사건번호 + 희망입찰가 만원단위 시뮬레이션)",
        ]
    )
    kb = {
        "inline_keyboard": [
            [
                {"text": "⚡ 예시: 2025타경 2768 (관악푸르지오) 즉시 분석", "callback_data": "prop:2025타경2768"},
            ],
            [
                {"text": "✨ 매력 매물 목록 보기", "callback_data": "menu:attractive"},
                {"text": "🏠 메인 메뉴", "callback_data": "menu:home"},
            ],
        ]
    }
    return text, kb


def build_property_detail_view(
    case_no: str, tab: str = "summary"
) -> tuple[str, Dict[str, Any]]:
    norm_case = normalize_case_no(case_no)
    prop = get_or_analyze_property_by_case_no(norm_case)
    if not prop or not prop.recommendation:
        return "해당 매물을 찾을 수 없습니다.", build_main_menu_keyboard()

    case_no = prop.case_no
    rec = prop.recommendation

    if tab == "summary":
        status_badge = "✅ 매력 매물 적합" if prop.is_attractive else "🚫 조건 미충족 주의"
        if prop.attractiveness_score >= 85:
            grade_str = "🌟 S등급 (초우량 매력 매물)"
        elif prop.attractiveness_score >= 75:
            grade_str = "✨ A등급 (우량 매력 매물)"
        elif prop.attractiveness_score >= 60:
            grade_str = "⚖️ B등급 (조건부 입찰 검토)"
        else:
            grade_str = "⚠️ C등급 (권리/수익 리스크 주의)"

        text = "\n".join(
            [
                f"🏛 <b>[{prop.case_no}] {prop.property_type} 권리관계 · 매력도 · 적정경매가 분석</b>",
                f"📊 <b>매력도 진단</b>: <b>{prop.attractiveness_score}점 / 100점</b> — <b>{grade_str}</b> ({status_badge})",
                f"📍 <b>소재지</b>: {prop.address} (전용 {prop.exclusive_area_m2}㎡ / 대지권 {prop.land_share_m2}㎡)",
                f"⚖️ <b>관할/기일</b>: {prop.court_name} | 매각기일 {prop.auction_date} ({prop.failed_count}회 유찰)",
                f"💰 <b>감정가</b>: {format_eok_man(prop.appraisal_price)} | <b>최저매각가</b>: {format_eok_man(prop.min_bid_price)}",
                "",
                "🛡 <b>[1. 권리관계 및 점유·관리비 분석 (매물이 어떤지)]</b>",
                f" • <b>말소기준권리/등기</b>: {prop.base_right_info}",
                f" • <b>권리상 하자 유무</b>: <b>{'하자 없음 (인수 권리 0원) ✔' if not prop.has_rights_defect else f'인수 하자 있음 ({format_eok_man(prop.assumed_rights_amount)}) ✖'}</b>",
                f" • <b>임차인/점유 현황</b>: <b>{'임차인 없음 ✔' if not prop.has_tenant else '임차인 있음 ✖'} · {prop.occupant_type} 거주 중</b> ({prop.occupancy_detail})",
                f" • <b>미납 관리비</b>: 총 {format_eok_man(prop.unpaid_mgmt_fee)} ({prop.unpaid_mgmt_months}개월분, 공용분 인수추산 <b>-{format_eok_man(rec.assumed_unpaid_mgmt_fee)}</b> 선제 차감)",
                "",
                "🏢 <b>[2. 6대 사이트 교차 시세 & 단지 가치]</b>",
                f" • <b>추정 기준시세</b>: <b>{format_eok_man(rec.estimated_market_value)}</b> (실거래 {format_eok_man(prop.molit.similar_area_avg_price)} · 디스코 {format_eok_man(prop.disco.nearby_sold_price_avg)} · 호가 {format_eok_man(prop.naver_land.asking_sale_min)})",
                f" • <b>건물연식/정비구역</b>: {prop.bdsplanet.built_year}년식({prop.bdsplanet.building_age_years}년차) | {prop.asil.redev_zone_name}",
                f" • <b>전세보증보험(126%) 한도</b>: {format_eok_man(prop.official_price.jeonse_insurance_limit)} (공시가 {format_eok_man(prop.official_price.official_price)})",
                "",
                "🎯 <b>[3. 추천 적정 경매가 & 예상 안전마진]</b>",
                f" • 보수적 입찰가 (확률 {rec.conservative_win_prob:.0f}%): {format_eok_man(rec.conservative_bid)}",
                f" ⭐ <b>적정 추천 경매가 (확률 {rec.optimal_win_prob:.0f}%): {format_eok_man(rec.optimal_bid)}</b> (감정가 대비 {rec.optimal_ratio_to_appraisal}% / 시세 대비 {rec.optimal_ratio_to_market}%)",
                f" • 공격형 입찰가 (확률 {rec.aggressive_win_prob:.0f}%): {format_eok_man(rec.aggressive_bid)}",
                f" 📈 <b>적정가 낙찰 시 순안전마진(실익)</b>: <b>+{format_eok_man(rec.expected_net_profit)}</b> (관리비·명도·취득세 차감 후)",
                "",
                "👇 <b>아래 버튼으로 6대 사이트 상세 데이터, 권리분석 근거, 입찰가 시뮬레이션을 확인하세요!</b>",
            ]
        )
    elif tab == "sites6":
        tx_lines = [
            f"   - {t.contract_date} {t.building_name}({t.floor}층): {format_eok_man(t.deal_amount)}"
            for t in prop.molit.transactions[:3]
        ]
        text = "\n".join(
            [
                f"🔍 <b>[{prop.case_no}] 6대 부동산 사이트 교차 분석 상세</b>",
                f"📍 {prop.address}",
                "",
                f"<b>① 디스코 (지도 실제 팔린 가격)</b>",
                f" • 인근 실매각 평균: <b>{format_eok_man(prop.disco.nearby_sold_price_avg)}</b> (평당 {format_eok_man(prop.disco.price_per_pyeong)})",
                f" • 최근 사례: {prop.disco.recent_sold_case} (거리 {prop.disco.distance_m}m)",
                "",
                f"<b>② 국토부 실거래 ({prop.molit.dong_name} 거래 통째 수집: {prop.molit.total_tx_count}건)</b>",
                f" • 유사면적 평균: <b>{format_eok_man(prop.molit.similar_area_avg_price)}</b> ({prop.molit.min_deal_price // 10000:,}만 ~ {prop.molit.max_deal_price // 10000:,}만)",
                *tx_lines,
                "",
                f"<b>③ 아실 (재개발 구역도 + 경매물건)</b>",
                f" • 정비구역: <b>{'🔥 포함 (' + prop.asil.redev_zone_name + ')' if prop.asil.is_redev_zone else '일반구역 (' + prop.asil.redev_zone_name + ')'}</b>",
                f" • 진행단계: {prop.asil.redev_stage}",
                f" • 아실 분석: {prop.asil.asil_case_summary}",
                "",
                f"<b>④ 부동산플래닛 (건물이 몇 년 됐는지)</b>",
                f" • 준공/연식: <b>{prop.bdsplanet.built_year}년 준공 ({prop.bdsplanet.building_age_years}년차)</b> | {prop.bdsplanet.age_condition_grade}",
                f" • 규모/구조: 총 {prop.bdsplanet.total_floors}층 / {prop.bdsplanet.structure_type}",
                "",
                f"<b>⑤ 공시가격알리미 (공시가 × 126% 전세보증보험 한도, 10월 기준)</b>",
                f" • 공시가격: {format_eok_man(prop.official_price.official_price)}",
                f" • <b>보증보험 한도(126%)</b>: <b>{format_eok_man(prop.official_price.jeonse_insurance_limit)}</b>",
                f" • 무피/레버리지: <b>{'💎 추천입찰가가 보증보험 한도 이내 (무피/초소액 세팅 가능!)' if prop.official_price.can_zero_gap_invest else '한도 초과분 자기자본 필요'}</b>",
                "",
                f"<b>⑥ 네이버부동산 (현재 시장 호가)</b>",
                f" • 매매 최저호가: <b>{format_eok_man(prop.naver_land.asking_sale_min)}</b> (평균 {format_eok_man(prop.naver_land.asking_sale_avg)})",
                f" • 전세 평균호가: <b>{format_eok_man(prop.naver_land.asking_jeonse_avg)}</b> (현재 매물 {prop.naver_land.active_listing_count}건)",
            ]
        )
    elif tab == "aitext":
        raw_ai_text = build_ai_discussion_text(prop, include_prompt=True)
        escaped_ai_text = html.escape(raw_ai_text)
        # Telegram message limit is 4096 chars
        if len(escaped_ai_text) > 3600:
            escaped_ai_text = escaped_ai_text[:3600] + "\n...(이하 생략)"
        text = "\n".join(
            [
                f"🤖 <b>[{prop.case_no}] 생성형 AI(제미나이·GPT) 토론용 상세 텍스트</b>",
                "💡 <i>아래 코드 블록을 터치(클릭)하면 전체 내용이 복사됩니다. 제미나이나 ChatGPT에 그대로 붙여넣어 토론을 시작하세요!</i>",
                "",
                f"<pre>{escaped_ai_text}</pre>",
            ]
        )
    else:  # rights tab
        rationale_lines = [f" • {r}" for r in rec.rationale]
        text = "\n".join(
            [
                f"🛡 <b>[{prop.case_no}] 권리·점유·미납관리비 & 입찰가 산정 근거</b>",
                f"📍 {prop.address}",
                "",
                "<b>1. 점유 및 임차인 현황</b>",
                f" • 임차인 존재 여부: <b>{'없음 (보증금 인수 위험 0원)' if not prop.has_tenant else '있음'}</b>",
                f" • 현재 점유자: <b>{prop.occupant_type}</b> ({prop.occupancy_detail})",
                "",
                "<b>2. 말소기준권리 및 등기 권리 분석</b>",
                f" • 권리상 하자: <b>{'없음' if not prop.has_rights_defect else '있음'}</b>",
                f" • 상세: {prop.base_right_info}",
                f" • 매수인 인수 권리 금액: <b>{format_eok_man(prop.assumed_rights_amount)}</b>",
                "",
                "<b>3. 미납 관리비 및 부대비용 차감 내역</b>",
                f" • 탐문 총 미납 관리비: <b>{format_eok_man(prop.unpaid_mgmt_fee)}</b> ({prop.unpaid_mgmt_months}개월 연체)",
                f" • 공용부분 인수 추산액(75%): <b>-{format_eok_man(rec.assumed_unpaid_mgmt_fee)}</b>",
                f" • 소유자 명도협의금 + 취득세 추정: <b>-{format_eok_man(rec.estimated_eviction_and_tax)}</b>",
                "",
                "<b>4. 입찰가 추천 산정 근거</b>",
                *rationale_lines,
            ]
        )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📋 종합 브리핑", "callback_data": f"prop:{case_no}"},
                {"text": "🔍 6대 사이트 상세", "callback_data": f"detail6:{case_no}"},
                {"text": "🛡 권리·관리비 상세", "callback_data": f"rights:{case_no}"},
            ],
            [
                {
                    "text": "🤖 AI 토론용 텍스트 추출 (제미나이 복사용)",
                    "callback_data": f"aitext:{case_no}",
                }
            ],
            [
                {"text": "🧮 보수적 입찰 시뮬", "callback_data": f"sim:{case_no}:cons"},
                {"text": "⭐ 적정 추천가 시뮬", "callback_data": f"sim:{case_no}:opt"},
                {"text": "🔥 공격형 입찰 시뮬", "callback_data": f"sim:{case_no}:agg"},
            ],
            [
                {
                    "text": "💎 공시가×126%(보증보험한도)로 입찰 시뮬레이션",
                    "callback_data": f"sim:{case_no}:ins",
                }
            ],
            [
                {"text": "⬅️ 매력 매물 목록으로", "callback_data": "menu:attractive"},
                {"text": "🏠 메인 메뉴", "callback_data": "menu:home"},
            ],
        ]
    }
    return text, keyboard


def build_simulation_view(case_no: str, mode_or_amount: str) -> tuple[str, Dict[str, Any]]:
    norm_case = normalize_case_no(case_no)
    prop = load_property_by_case_no(norm_case)
    if not prop or not prop.recommendation:
        hist_rec = load_winning_record_by_case_no(norm_case)
        if hist_rec:
            if mode_or_amount == "cons":
                bid_amount = hist_rec.suggested_conservative_bid
                label = "당시 제시 보수적 입찰가"
            elif mode_or_amount == "opt":
                bid_amount = hist_rec.suggested_optimal_bid
                label = "⭐ 당시 제시 적정 입찰가"
            elif mode_or_amount == "agg":
                bid_amount = hist_rec.suggested_aggressive_bid
                label = "🔥 당시 제시 공격형 입찰가"
            else:
                bid_amount = int(mode_or_amount)
                label = "사용자 직접 입력 입찰가"

            hsim = simulate_custom_bid_on_history(hist_rec, bid_amount)
            gap_1st = int(hsim["gap_vs_1st"])
            gap_2nd = int(hsim["gap_vs_2nd"])
            gap_1st_sign = "+" if gap_1st >= 0 else "-"
            gap_2nd_sign = "+" if gap_2nd >= 0 else "-"
            text = "\n".join(
                [
                    f"🧮 <b>[{hist_rec.case_no}] 과거 낙찰건 백테스팅 시뮬레이션</b>",
                    f"📍 {hist_rec.region_name} ({hist_rec.property_type}, {hist_rec.exclusive_area_m2}㎡)",
                    f"🏷 <b>시뮬레이션 기준</b>: {label}",
                    "━━━━━━━━━━━━━━━━━━━━",
                    f"💵 <b>시뮬레이션 입찰가</b>: <b>{format_eok_man(bid_amount)}</b>",
                    f" • 당시 제시 적정가: <b>{format_eok_man(hist_rec.suggested_optimal_bid)}</b>",
                    f" • 실제 1등 낙찰가: <b>{format_eok_man(hist_rec.winning_bid_price)}</b>",
                    f" • 실제 2등(차순위) 입찰가: <b>{format_eok_man(hist_rec.second_bid_price)}</b>",
                    "",
                    "🏆 <b>[낙찰 여부 및 2등과의 격차 분석]</b>",
                    f" • 판정 결과: <b>{hsim['rank_label']}</b>",
                    f" • <b>실제 1등 vs 2등 차이</b>: <b>+{format_eok_man(hist_rec.gap_1st_to_2nd_price)}</b> (감정가 대비 {hist_rec.gap_1st_to_2nd_ratio}%p)",
                    f" • <b>내 입찰가 vs 2등 차이</b>: <b>{gap_2nd_sign}{format_eok_man(abs(gap_2nd))}</b>",
                    f" • <b>내 입찰가 vs 1등 차이</b>: <b>{gap_1st_sign}{format_eok_man(abs(gap_1st))}</b>",
                    "",
                    "💰 <b>[만약 낙찰되었다면 얼마나 이득이었나?]</b>",
                    f" • 당시 실거래 시세: {format_eok_man(hist_rec.market_value_at_bid)}",
                    f" • 공용관리비·명도·취득세 차감: -{format_eok_man(hist_rec.assumed_unpaid_mgmt_fee + hist_rec.estimated_eviction_and_tax)}",
                    f" • 👉 <b>이 금액 낙찰 시 순수익(이득)</b>: <b>+{format_eok_man(int(hsim['simulated_net_profit']))}</b>",
                    f" • 제시 적정가 낙찰 가정 시 순수익: <b>+{format_eok_man(hist_rec.suggested_optimal_net_profit)}</b>",
                    f" • 실제 1등 낙찰자의 순수익: <b>+{format_eok_man(hist_rec.actual_winner_net_profit)}</b>",
                    "",
                    f"💡 <b>상세 요약</b>: {hsim['detail_message']}",
                ]
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "📊 과거 낙찰 시뮬레이션 목록", "callback_data": "menu:history"},
                        {"text": "🏠 메인 메뉴", "callback_data": "menu:home"},
                    ]
                ]
            }
            return text, kb

        # DB에 없으면 실시간 분석 후 시뮬레이션
        prop = get_or_analyze_property_by_case_no(norm_case)
        if not prop or not prop.recommendation:
            return "매물 정보를 찾을 수 없습니다.", build_main_menu_keyboard()

    case_no = prop.case_no
    rec = prop.recommendation
    if mode_or_amount == "cons":
        bid_amount = rec.conservative_bid
        label = "보수적(고마진형) 입찰가"
    elif mode_or_amount == "opt":
        bid_amount = rec.optimal_bid
        label = "⭐ 적정 추천 입찰가"
    elif mode_or_amount == "agg":
        bid_amount = rec.aggressive_bid
        label = "공격형(낙찰우선) 입찰가"
    elif mode_or_amount == "ins":
        bid_amount = prop.official_price.jeonse_insurance_limit
        label = "⑤ 공시가×126% 전세보증보험 한도액 기준"
    else:
        bid_amount = int(mode_or_amount)
        label = "사용자 직접 입력 입찰가"

    sim = simulate_bid_for_property(prop, bid_amount)
    text = "\n".join(
        [
            f"🧮 <b>[{prop.case_no}] 입찰가 시뮬레이션 결과</b>",
            f"📍 {prop.address}",
            f"🏷 <b>시뮬레이션 기준</b>: {label}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>투입 입찰가</b>: <b>{format_eok_man(bid_amount)}</b>",
            f" • 감정가 대비: {sim['ratio_to_appraisal']}% | 실거래 시세 대비: {sim['ratio_to_market']}%",
            f"🎯 <b>예상 낙찰 가능성(확률)</b>: <b>{sim['estimated_win_probability']}%</b>",
            "",
            "💰 <b>[수익 및 레버리지 분석]</b>",
            f" • 6대 사이트 교차 추정시세: {format_eok_man(rec.estimated_market_value)}",
            f" • 미납관리비(공용분) 인수 차감: -{format_eok_man(int(sim['assumed_unpaid_mgmt_fee']))}",
            f" • 명도비·취득세 차감 후 <b>순안전마진</b>: <b>{format_eok_man(int(sim['expected_net_profit']))}</b>",
            f" • ⑤ 공시가×126% 보증보험 한도: {format_eok_man(int(sim['jeonse_insurance_limit_126']))}",
            f" • 보증보험 전세 세팅 시 <b>실투입 자기자본</b>: <b>{format_eok_man(int(sim['self_capital_with_jeonse_leverage']))}</b>",
            "",
            f"💡 <b>종합 판정</b>: <b>{sim['verdict']}</b>",
            "",
            f"✍️ <i>다른 금액을 계산해보려면 채팅창에 <code>{case_no} 102000</code> 처럼 (사건번호 + 만원단위 금액)을 입력해보세요!</i>",
        ]
    )

    _, kb = build_property_detail_view(case_no, tab="summary")
    return text, kb


def build_history_view() -> tuple[str, Dict[str, Any]]:
    ensure_seeded()
    history = load_winning_history()
    avg_app = sum(h.winning_bid_ratio_appraisal for h in history) / len(history)
    avg_mkt = sum(h.winning_bid_ratio_market for h in history) / len(history)
    avg_sugg_profit = int(sum(h.suggested_optimal_net_profit for h in history) / len(history))
    avg_gap_2nd = int(sum(h.gap_1st_to_2nd_price for h in history) / len(history))
    beat_2nd_cnt = sum(1 for h in history if h.would_beat_2nd_with_optimal)
    win_opt_cnt = sum(1 for h in history if h.would_win_with_optimal)

    lines = [
        f"📊 <b>[과거 낙찰 데이터 기준: 제시 낙찰가 · 이득(순수익) · 2등 격차 시뮬레이션 ({len(history)}건)]</b>",
        "조건: <b>임차인 없음 · 소유자 거주 · 권리하자 없음</b>",
        f"• 평균 낙찰가율: 감정 <b>{avg_app:.1f}%</b> / 시세 <b>{avg_mkt:.1f}%</b>",
        f"• 제시 적정가 낙찰 시 평균 이득(순수익): <b>+{format_eok_man(avg_sugg_profit)}</b>",
        f"• 실제 1등과 2등(차순위) 평균 격차: <b>+{format_eok_man(avg_gap_2nd)}</b>",
        f"• 시뮬레이션 적중: <b>2등 제침 {beat_2nd_cnt}/{len(history)}건</b> (적정가 1등 낙찰 {win_opt_cnt}건 · 공격형 1등 {len(history)}건)",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    inline_rows: List[List[Dict[str, str]]] = []
    for idx, h in enumerate(history[:8], 1):
        redev = "🔥재개발" if h.is_redev_zone else "일반"
        sugg_2nd_sign = "+" if h.gap_suggested_to_2nd >= 0 else "-"
        lines.append(
            f"\n<b>{idx}. [{h.case_no}] {h.region_name} ({h.property_type}, {redev})</b>\n"
            f"  감정 {format_eok_man(h.appraisal_price)} | 당시시세 {format_eok_man(h.market_value_at_bid)}\n"
            f"  🎯 <b>제시된 낙찰가(추천): {format_eok_man(h.suggested_optimal_bid)}</b> (공격 {format_eok_man(h.suggested_aggressive_bid)})\n"
            f"  🏆 <b>실제 1등: {format_eok_man(h.winning_bid_price)}</b> | 🥈 <b>2등: {format_eok_man(h.second_bid_price)}</b> (응찰 {h.bidders_count}명)\n"
            f"  📏 <b>2등과의 차이</b>: 1등은 2등보다 <b>+{format_eok_man(h.gap_1st_to_2nd_price)}</b> 더 씀 | 제시가는 2등 대비 <b>{sugg_2nd_sign}{format_eok_man(abs(h.gap_suggested_to_2nd))}</b>\n"
            f"  💰 <b>낙찰 시 이득(순수익)</b>: 제시가 낙찰 시 <b>+{format_eok_man(h.suggested_optimal_net_profit)}</b> 이득 (실제 1등 순수익 +{format_eok_man(h.actual_winner_net_profit)})\n"
            f"  📌 {h.simulation_badge}"
        )
        inline_rows.append(
            [
                {
                    "text": f"🧮 {idx}번 [{h.case_no}] 제시가 시뮬 상세",
                    "callback_data": f"sim:{h.case_no}:opt",
                },
                {
                    "text": f"🔥 공격형 시뮬",
                    "callback_data": f"sim:{h.case_no}:agg",
                },
            ]
        )

    inline_rows.append(
        [
            {"text": "✨ 진행중 매력 매물 목록", "callback_data": "menu:attractive"},
            {"text": "🏠 메인 메뉴로", "callback_data": "menu:home"},
        ]
    )
    kb = {"inline_keyboard": inline_rows}
    return "\n".join(lines), kb


async def send_telegram_case_analysis(case_no: str) -> Dict[str, Any]:
    """특정 사건번호(예: 2025타경 2768) 분석 브리핑을 사용자의 텔레그램으로 즉시 발송합니다."""
    chat_id, active_token = get_bot2_credentials()
    if not chat_id or not active_token:
        return {
            "ok": False,
            "error": "~/.env 파일에 TELEGRAM_USER_ID 또는 TELEGRAM_BOT_2 토큰이 없습니다.",
        }

    norm_case = normalize_case_no(case_no)
    text, kb = build_property_detail_view(norm_case, tab="summary")

    async with httpx.AsyncClient(timeout=15.0) as client:
        me_resp = await client.get(f"https://api.telegram.org/bot{active_token}/getMe")
        used_bot_username = (
            me_resp.json().get("result", {}).get("username", "TELEGRAM_BOT_2")
            if me_resp.status_code == 200
            else "TELEGRAM_BOT_2"
        )
        r = await client.post(
            f"https://api.telegram.org/bot{active_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": kb,
            },
        )
        data = r.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("description", "텔레그램 발송 실패")}

    return {
        "ok": True,
        "case_no": norm_case,
        "bot_username": used_bot_username,
        "message_id": data["result"]["message_id"],
    }


async def send_telegram_report(
    attractive_props: List[AuctionProperty],
    history: List[WinningBidRecord],
    dashboard_url: Optional[str] = None,
) -> Dict[str, Any]:
    """~/.env의 TELEGRAM_BOT_2 와 TELEGRAM_USER_ID를 사용하여 앱 버튼(Inline + Reply Keyboard)이 포함된 대화형 리포트 발송"""
    if dashboard_url is None:
        dashboard_url = f"http://localhost:{settings.PORT}"
    chat_id, active_token = get_bot2_credentials()
    if not chat_id or not active_token:
        return {
            "ok": False,
            "error": "~/.env 파일에 TELEGRAM_USER_ID 또는 TELEGRAM_BOT_2 토큰이 없습니다.",
        }

    sent_message_ids: List[int] = []
    used_bot_username = "TELEGRAM_BOT_2"

    avg_sugg_profit = (
        int(sum(h.suggested_optimal_net_profit for h in history) / len(history))
        if history
        else 0
    )
    avg_gap_2nd = (
        int(sum(h.gap_1st_to_2nd_price for h in history) / len(history))
        if history
        else 0
    )

    welcome_text = "\n".join(
        [
            "🏛 <b>[AuctionRadar] 대화형 경매 매력물건 발굴 & 사건번호 즉시분석 리포트</b>",
            "",
            "🔎 <b>사건번호 즉시 분석 기능 안내</b>",
            " • 채팅창에 <code>2025타경 2768</code> 처럼 <b>사건번호</b>를 입력하시면 권리관계·임차인·미납관리비·매력도 점수와 <b>적정 경매가(3단계)</b>를 즉시 알려드립니다!",
            "",
            "✅ <b>자동 추려내기 완료 기준</b>",
            " • 임차인 없음 + 소유자 거주 중 + 권리상 하자 없음 + 미납관리비 검증",
            " • ①디스코 · ②국토부실거래 · ③아실 · ④부동산플래닛 · ⑤공시가격알리미(126%) · ⑥네이버부동산 교차분석 완료",
            "",
            "📊 <b>과거 낙찰 백테스팅 시뮬레이션 요약</b>",
            f" • 과거 낙찰 {len(history)}건 기준 제시 적정가 낙찰 시 평균 이득: <b>+{format_eok_man(avg_sugg_profit)}</b>",
            f" • 실제 1등 낙찰자와 2등(차순위) 평균 격차: <b>+{format_eok_man(avg_gap_2nd)}</b>",
            "",
            f"📌 현재 조건 충족 매력 매물 <b>{len(attractive_props)}건</b>과 과거 낙찰 시뮬레이션 리포트 <b>{len(history)}건</b>을 함께 전송합니다.",
        ]
    )

    list_text, list_kb = build_property_list_view("attractive")
    hist_text, hist_kb = build_history_view()

    async with httpx.AsyncClient(timeout=15.0) as client:
        me_resp = await client.get(f"https://api.telegram.org/bot{active_token}/getMe")
        if me_resp.status_code == 200:
            used_bot_username = me_resp.json().get("result", {}).get("username", "TELEGRAM_BOT_2")
        else:
            return {"ok": False, "error": f"TELEGRAM_BOT_2 인증 실패 ({me_resp.text})"}

        # 1) 하단 고정 앱 키보드(ReplyKeyboardMarkup) 활성화 메시지
        r1 = await client.post(
            f"https://api.telegram.org/bot{active_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": welcome_text,
                "parse_mode": "HTML",
                "reply_markup": build_persistent_reply_keyboard(),
            },
        )
        d1 = r1.json()
        if d1.get("ok"):
            sent_message_ids.append(d1["result"]["message_id"])

        # 2) 인라인 버튼(InlineKeyboardMarkup) 진행중 매력 매물 선택 메시지
        r2 = await client.post(
            f"https://api.telegram.org/bot{active_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": list_text,
                "parse_mode": "HTML",
                "reply_markup": list_kb,
            },
        )
        d2 = r2.json()
        if d2.get("ok"):
            sent_message_ids.append(d2["result"]["message_id"])

        # 3) 과거 낙찰 데이터 기준 제시된 낙찰가 · 낙찰 시 이득 · 2등과의 격차 시뮬레이션 리포트 메시지
        r3 = await client.post(
            f"https://api.telegram.org/bot{active_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": hist_text,
                "parse_mode": "HTML",
                "reply_markup": hist_kb,
            },
        )
        d3 = r3.json()
        if d3.get("ok"):
            sent_message_ids.append(d3["result"]["message_id"])

    masked_chat_id = f"{chat_id[:3]}****" if len(chat_id) > 3 else "****"
    return {
        "ok": True,
        "bot_key": "TELEGRAM_BOT_2",
        "bot_username": used_bot_username,
        "chat_id": masked_chat_id,
        "messages_sent": len(sent_message_ids),
        "message_ids": sent_message_ids,
    }


class TelegramBotPoller:
    """텔레그램 앱 버튼 클릭(callback_query) 및 하단 메뉴 버튼/채팅 입력을 실시간 처리하는 백그라운드 워커"""

    def __init__(self) -> None:
        self.offset: int = 0
        self.running: bool = False
        self.last_viewed_case_no: str = "2025타경2768"

    async def start(self) -> None:
        self.running = True
        _, token = get_bot2_credentials()
        if not token:
            return

        async with httpx.AsyncClient(timeout=25.0) as client:
            # 봇 명령어 메뉴 등록 (setMyCommands)
            await client.post(
                f"https://api.telegram.org/bot{token}/setMyCommands",
                json={
                    "commands": [
                        {"command": "start", "description": "🏠 메인 메뉴 및 앱 버튼 열기"},
                        {"command": "case", "description": "🔎 사건번호로 권리관계·매력도·적정경매가 분석 (예: /case 2025타경 2768)"},
                        {"command": "attractive", "description": "✨ 추려낸 매력 매물 목록 보기"},
                        {"command": "redev", "description": "🔥 아실 재개발 구역 매물 보기"},
                        {"command": "zerogap", "description": "💎 공시가×126% 보증보험 한도 내 매물"},
                        {"command": "history", "description": "📊 최근 유사 매물 실제 낙찰가율 추적"},
                        {"command": "scrape", "description": "🔄 6대 사이트 즉시 재스크래핑 실행"},
                    ]
                },
            )

            while self.running:
                try:
                    resp = await client.get(
                        f"https://api.telegram.org/bot{token}/getUpdates",
                        params={"offset": self.offset, "timeout": 15},
                    )
                    if resp.status_code != 200:
                        await asyncio.sleep(2)
                        continue

                    updates = resp.json().get("result", [])
                    for upd in updates:
                        self.offset = upd["update_id"] + 1
                        await self.handle_update(client, token, upd)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(2)

    async def handle_update(
        self, client: httpx.AsyncClient, token: str, upd: Dict[str, Any]
    ) -> None:
        # 1. 인라인 버튼 클릭 (callback_query) 처리
        if "callback_query" in upd:
            cq = upd["callback_query"]
            cq_id = cq["id"]
            data = cq.get("data", "")
            msg = cq.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            message_id = msg.get("message_id")

            await client.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": cq_id, "text": "처리 중..."},
            )

            text, reply_markup = self.route_callback(data)
            if chat_id and message_id:
                await client.post(
                    f"https://api.telegram.org/bot{token}/editMessageText",
                    json={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup,
                    },
                )
            return

        # 2. 하단 고정 키보드 버튼 또는 텍스트 명령어 처리
        if "message" in upd:
            msg = upd["message"]
            chat_id = msg.get("chat", {}).get("id")
            user_text = (msg.get("text") or "").strip()
            if not chat_id or not user_text:
                return

            text, reply_markup = self.route_message_text(user_text)
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup,
                },
            )

    def route_callback(self, data: str) -> tuple[str, Dict[str, Any]]:
        if data == "menu:home":
            return (
                "🏛 <b>[AuctionRadar 메인 메뉴]</b>\n원하시는 메뉴 버튼을 선택하거나, 채팅창에 <code>2025타경 2768</code> 처럼 사건번호를 입력해주세요.",
                build_main_menu_keyboard(),
            )
        if data == "menu:lookup_help":
            return build_lookup_help_view()
        if data.startswith("menu:"):
            mode = data.split(":", 1)[1]
            if mode == "history":
                return build_history_view()
            return build_property_list_view(mode)

        if data == "action:scrape":
            props, history = run_scraping_and_analysis_pipeline()
            save_pipeline_results(props, history)
            text, kb = build_property_list_view("attractive")
            return f"✅ <b>6대 부동산 사이트 최신 스크래핑 & 재분석 완료!</b>\n\n{text}", kb

        if data.startswith("prop:"):
            case_no = normalize_case_no(data.split(":", 1)[1])
            self.last_viewed_case_no = case_no
            return build_property_detail_view(case_no, tab="summary")

        if data.startswith("detail6:"):
            case_no = normalize_case_no(data.split(":", 1)[1])
            self.last_viewed_case_no = case_no
            return build_property_detail_view(case_no, tab="sites6")

        if data.startswith("rights:"):
            case_no = normalize_case_no(data.split(":", 1)[1])
            self.last_viewed_case_no = case_no
            return build_property_detail_view(case_no, tab="rights")

        if data.startswith("aitext:"):
            case_no = normalize_case_no(data.split(":", 1)[1])
            self.last_viewed_case_no = case_no
            return build_property_detail_view(case_no, tab="aitext")

        if data.startswith("sim:"):
            _, case_no, mode = data.split(":", 2)
            case_no = normalize_case_no(case_no)
            self.last_viewed_case_no = case_no
            return build_simulation_view(case_no, mode)

        return "메뉴를 선택해주세요.", build_main_menu_keyboard()

    def route_message_text(self, user_text: str) -> tuple[str, Dict[str, Any]]:
        cleaned = user_text.strip()
        if cleaned in ("/start", "🏠 메인 메뉴"):
            return (
                "🏛 <b>[AuctionRadar 대화형 컨트롤러]</b>\n채팅창에 <code>2025타경 2768</code> 처럼 사건번호를 입력하면 <b>권리관계 · 매력도 · 적정 경매가</b>를 즉시 분석해 드립니다!",
                build_main_menu_keyboard(),
            )
        if cleaned in ("/lookup", "🔎 사건번호 조회 안내"):
            return build_lookup_help_view()
        if cleaned in ("/attractive", "✨ 매력 매물 목록"):
            return build_property_list_view("attractive")
        if cleaned in ("/redev", "🔥 재개발 매물"):
            return build_property_list_view("redev")
        if cleaned in ("/zerogap", "💎 보증보험 126% 매물"):
            return build_property_list_view("zerogap")
        if cleaned in ("/history", "📊 낙찰가율 추적 DB"):
            return build_history_view()
        if cleaned in ("/scrape", "🔄 즉시 재스크래핑"):
            props, history = run_scraping_and_analysis_pipeline()
            save_pipeline_results(props, history)
            text, kb = build_property_list_view("attractive")
            return f"✅ <b>6대 사이트 스크래핑 및 입찰가 재산출 완료!</b>\n\n{text}", kb

        # 0) "/ai 2025타경 2768" 또는 "2025타경 2768 텍스트" 명령어 처리 (AI 토론용 상세 텍스트 추출)
        ai_cmd_match = re.match(
            r"^(?:/ai|/prompt|ai|프롬프트|텍스트)\s*(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if ai_cmd_match:
            norm_case = normalize_case_no(ai_cmd_match.group(1).strip())
            self.last_viewed_case_no = norm_case
            return build_property_detail_view(norm_case, tab="aitext")

        # 1) "/case 2025타경 2768" 또는 "/조회 2025타경2768" 명령어 처리
        cmd_match = re.match(
            r"^(?:/case|/analyze|/조회|조회|분석)\s*(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if cmd_match:
            arg = cmd_match.group(1).strip()
            if not arg:
                return build_lookup_help_view()
            norm_case = normalize_case_no(arg)
            self.last_viewed_case_no = norm_case
            return build_property_detail_view(norm_case, tab="summary")

        # 2) 사건번호 + 희망입찰가 시뮬레이션 (예: "2025타경 2768 102000", "2026타경104821 80000")
        sim_with_case = re.match(
            r"^(20\d{2}\s*타\s*경\s*\d+)\s+([0-9,]{4,10})\s*(?:만원?)?$",
            cleaned,
        )
        if sim_with_case:
            norm_case = normalize_case_no(sim_with_case.group(1))
            self.last_viewed_case_no = norm_case
            raw_num = int(sim_with_case.group(2).replace(",", ""))
            bid_won = raw_num * 10_000 if raw_num < 10_000_000 else raw_num
            return build_simulation_view(norm_case, str(bid_won))

        # 3) 사건번호 단독 입력 (예: "2025타경 2768", "2025타경2768", "2025 타경 2768 알려줘")
        case_only_match = re.search(r"(20\d{2}\s*타\s*경\s*\d+)", cleaned)
        if case_only_match:
            norm_case = normalize_case_no(case_only_match.group(1))
            self.last_viewed_case_no = norm_case
            return build_property_detail_view(norm_case, tab="summary")

        # 4) 금액만 단독 입력 시 최근 조회한 사건번호에 대해 입찰가 시뮬레이션 (예: "80000", "102000만원")
        amount_only_match = re.match(r"^([0-9,]{4,10})\s*(?:만원?)?$", cleaned)
        if amount_only_match:
            raw_num = int(amount_only_match.group(1).replace(",", ""))
            bid_won = raw_num * 10_000 if raw_num < 10_000_000 else raw_num
            return build_simulation_view(self.last_viewed_case_no, str(bid_won))

        return (
            "🏛 사건번호 분석을 원하시면 <code>2025타경 2768</code> 처럼 입력하시거나, 입찰가 시뮬레이션은 <code>2025타경 2768 102000</code> 형태로 입력해보세요!",
            build_main_menu_keyboard(),
        )


bot_poller = TelegramBotPoller()


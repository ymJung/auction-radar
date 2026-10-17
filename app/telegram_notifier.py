import asyncio
import os
import re
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv

from app.analyzer import simulate_bid_for_property
from app.config import HOME_ENV_PATH, settings
from app.database import (
    ensure_seeded,
    load_all_properties,
    load_property_by_case_no,
    load_winning_history,
    save_pipeline_results,
)
from app.models import AuctionProperty, WinningBidRecord
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
                {"text": "✨ 매력 매물 TOP 5 (클릭해서 상세)", "callback_data": "menu:attractive"},
            ],
            [
                {"text": "🔥 ③ 아실 재개발 구역 매물", "callback_data": "menu:redev"},
                {"text": "💎 ⑤ 공시가×126% 무피/소액", "callback_data": "menu:zerogap"},
            ],
            [
                {"text": "📊 실제 낙찰가율 추적 현황", "callback_data": "menu:history"},
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
            [{"text": "✨ 매력 매물 목록"}, {"text": "🔥 재개발 매물"}, {"text": "💎 보증보험 126% 매물"}],
            [{"text": "📊 낙찰가율 추적 DB"}, {"text": "🔄 즉시 재스크래핑"}, {"text": "🏠 메인 메뉴"}],
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

    buttons.append([{"text": "🏠 메인 메뉴로", "callback_data": "menu:home"}])
    return "\n".join(lines), {"inline_keyboard": buttons}


def build_property_detail_view(
    case_no: str, tab: str = "summary"
) -> tuple[str, Dict[str, Any]]:
    prop = load_property_by_case_no(case_no)
    if not prop or not prop.recommendation:
        return "해당 매물을 찾을 수 없습니다.", build_main_menu_keyboard()

    rec = prop.recommendation

    if tab == "summary":
        status_badge = "✅ 매력 매물 적합" if prop.is_attractive else "🚫 조건 미충족 제외"
        text = "\n".join(
            [
                f"🏛 <b>[{prop.case_no}] {prop.property_type} 종합 브리핑</b> ({status_badge} · {prop.attractiveness_score}점)",
                f"📍 <b>주소</b>: {prop.address} (전용 {prop.exclusive_area_m2}㎡ / 대지권 {prop.land_share_m2}㎡)",
                f"⚖️ <b>법원/기일</b>: {prop.court_name} | {prop.auction_date} ({prop.failed_count}회 유찰)",
                f"💰 <b>감정가</b>: {format_eok_man(prop.appraisal_price)} | <b>최저가</b>: {format_eok_man(prop.min_bid_price)}",
                "",
                "🛡 <b>[핵심 필터 조건 검증]</b>",
                f" • 임차인 유무: <b>{'임차인 없음 ✔' if not prop.has_tenant else '임차인 있음 ✖'}</b>",
                f" • 거주 상태: <b>{prop.occupant_type} 거주 중</b> ({prop.occupancy_detail})",
                f" • 권리 하자: <b>{'하자 없음 (인수 0원) ✔' if not prop.has_rights_defect else '인수 하자 있음 ✖'}</b>",
                f" • 미납 관리비: <b>총 {format_eok_man(prop.unpaid_mgmt_fee)}</b> (공용분 인수추산 {format_eok_man(rec.assumed_unpaid_mgmt_fee)} 차감)",
                "",
                "🎯 <b>[낙찰 추적 기반 AI 추천 입찰가]</b>",
                f" • 보수적(확률 {rec.conservative_win_prob:.0f}%): {format_eok_man(rec.conservative_bid)}",
                f" 👉 <b>적정 추천가(확률 {rec.optimal_win_prob:.0f}%): {format_eok_man(rec.optimal_bid)}</b>",
                f" • 공격형(확률 {rec.aggressive_win_prob:.0f}%): {format_eok_man(rec.aggressive_bid)}",
                f" 📈 <b>적정가 낙찰 시 순안전마진</b>: <b>+{format_eok_man(rec.expected_net_profit)}</b>",
                "",
                "👇 <b>아래 버튼을 눌러 6대 사이트 분석이나 입찰가 시뮬레이션을 실행하세요!</b>",
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
                f" • 정비구역: <b>{'🔥 포함 (' + prop.asil.redev_zone_name + ')' if prop.asil.is_redev_zone else '일반구역'}</b>",
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
    prop = load_property_by_case_no(case_no)
    if not prop or not prop.recommendation:
        return "매물 정보를 찾을 수 없습니다.", build_main_menu_keyboard()

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
            f"✍️ <i>다른 금액을 계산해보려면 채팅창에 <code>{case_no} 78000</code> 처럼 (사건번호 + 만원단위 금액)을 입력해보세요!</i>",
        ]
    )

    _, kb = build_property_detail_view(case_no, tab="summary")
    return text, kb


def build_history_view() -> tuple[str, Dict[str, Any]]:
    ensure_seeded()
    history = load_winning_history()
    avg_app = sum(h.winning_bid_ratio_appraisal for h in history) / len(history)
    avg_mkt = sum(h.winning_bid_ratio_market for h in history) / len(history)

    lines = [
        f"📊 <b>[유사 조건 실제 낙찰 결과 추적 DB ({len(history)}건)]</b>",
        "조건: <b>임차인 없음 · 소유자 거주 · 권리하자 없음</b>",
        f"• 평균 감정가 대비 낙찰가율: <b>{avg_app:.1f}%</b>",
        f"• 평균 실거래 시세 대비 낙찰가율: <b>{avg_mkt:.1f}%</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for h in history[:8]:
        redev = "🔥재개발" if h.is_redev_zone else "일반"
        lines.append(
            f"• <b>{h.sold_date} | {h.region_name} ({h.property_type}, {h.building_age_years}년차, {redev})</b>\n"
            f"  감정 {format_eok_man(h.appraisal_price)} / 당시시세 {format_eok_man(h.market_value_at_bid)}\n"
            f"  👉 <b>낙찰 {format_eok_man(h.winning_bid_price)}</b> (감정 <b>{h.winning_bid_ratio_appraisal}%</b> · 시세 <b>{h.winning_bid_ratio_market}%</b> | 응찰 {h.bidders_count}명)"
        )

    kb = {
        "inline_keyboard": [
            [{"text": "✨ 매력 매물 목록 보기", "callback_data": "menu:attractive"}],
            [{"text": "🏠 메인 메뉴로", "callback_data": "menu:home"}],
        ]
    }
    return "\n".join(lines), kb


async def send_telegram_report(
    attractive_props: List[AuctionProperty],
    history: List[WinningBidRecord],
    dashboard_url: str = "http://localhost:8000",
) -> Dict[str, Any]:
    """~/.env의 TELEGRAM_BOT_2 와 TELEGRAM_USER_ID를 사용하여 앱 버튼(Inline + Reply Keyboard)이 포함된 대화형 리포트 발송"""
    chat_id, active_token = get_bot2_credentials()
    if not chat_id or not active_token:
        return {
            "ok": False,
            "error": "~/.env 파일에 TELEGRAM_USER_ID 또는 TELEGRAM_BOT_2 토큰이 없습니다.",
        }

    sent_message_ids: List[int] = []
    used_bot_username = "TELEGRAM_BOT_2"

    welcome_text = "\n".join(
        [
            "🏛 <b>[AuctionRadar] 대화형 경매 매력물건 발굴 & 입찰 추천 봇</b>",
            "",
            "✅ <b>자동 추려내기 완료 기준</b>",
            " • 임차인 없음 + 소유자 거주 중 + 권리상 하자 없음 + 미납관리비 검증",
            " • ①디스코 · ②국토부실거래 · ③아실 · ④부동산플래닛 · ⑤공시가격알리미(126%) · ⑥네이버부동산 교차분석 완료",
            "",
            f"📌 현재 조건 충족 매력 매물 <b>{len(attractive_props)}건</b>과 과거 낙찰 추적 <b>{len(history)}건</b>이 준비되었습니다.",
            "👇 <b>아래 앱 버튼을 눌러 매물별 상세 분석과 입찰가 시뮬레이션을 조작해보세요!</b>",
        ]
    )

    list_text, list_kb = build_property_list_view("attractive")

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

        # 2) 인라인 버튼(InlineKeyboardMarkup) 매물 선택 메뉴 메시지
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
        self.last_viewed_case_no: str = "2026타경104821"

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
                        {"command": "attractive", "description": "✨ 추려낸 매력 매물 TOP 5 보기"},
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
                "🏛 <b>[AuctionRadar 메인 메뉴]</b>\n원하시는 메뉴 버튼을 선택해주세요.",
                build_main_menu_keyboard(),
            )
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
            case_no = data.split(":", 1)[1]
            self.last_viewed_case_no = case_no
            return build_property_detail_view(case_no, tab="summary")

        if data.startswith("detail6:"):
            case_no = data.split(":", 1)[1]
            self.last_viewed_case_no = case_no
            return build_property_detail_view(case_no, tab="sites6")

        if data.startswith("rights:"):
            case_no = data.split(":", 1)[1]
            self.last_viewed_case_no = case_no
            return build_property_detail_view(case_no, tab="rights")

        if data.startswith("sim:"):
            _, case_no, mode = data.split(":", 2)
            self.last_viewed_case_no = case_no
            return build_simulation_view(case_no, mode)

        return "메뉴를 선택해주세요.", build_main_menu_keyboard()

    def route_message_text(self, user_text: str) -> tuple[str, Dict[str, Any]]:
        if user_text in ("/start", "🏠 메인 메뉴"):
            return (
                "🏛 <b>[AuctionRadar 대화형 컨트롤러]</b>\n아래 인라인 버튼이나 하단 앱 버튼으로 매물 조회 및 입찰가 추천 시뮬레이션을 이용하세요!",
                build_main_menu_keyboard(),
            )
        if user_text in ("/attractive", "✨ 매력 매물 목록"):
            return build_property_list_view("attractive")
        if user_text in ("/redev", "🔥 재개발 매물"):
            return build_property_list_view("redev")
        if user_text in ("/zerogap", "💎 보증보험 126% 매물"):
            return build_property_list_view("zerogap")
        if user_text in ("/history", "📊 낙찰가율 추적 DB"):
            return build_history_view()
        if user_text in ("/scrape", "🔄 즉시 재스크래핑"):
            props, history = run_scraping_and_analysis_pipeline()
            save_pipeline_results(props, history)
            text, kb = build_property_list_view("attractive")
            return f"✅ <b>6대 사이트 스크래핑 및 입찰가 재산출 완료!</b>\n\n{text}", kb

        # "2026타경104821 80000" 또는 "80000" 형태의 입찰가 직접 시뮬레이션 지원
        m = re.match(r"^(?:(\d{4}타경\d+)\s+)?([0-9,]{4,10})\s*(?:만원?)?$", user_text)
        if m:
            case_no = m.group(1) or self.last_viewed_case_no
            raw_num = int(m.group(2).replace(",", ""))
            bid_won = raw_num * 10_000 if raw_num < 10_000_000 else raw_num
            return build_simulation_view(case_no, str(bid_won))

        return (
            "🏛 아래 버튼을 클릭하거나, 입찰가 시뮬레이션을 원하시면 <code>2026타경104821 81000</code> (사건번호 + 만원단위 입찰가) 형태로 입력해보세요!",
            build_main_menu_keyboard(),
        )


bot_poller = TelegramBotPoller()

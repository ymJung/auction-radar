from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.analyzer import (
    DEFAULT_FUNDING_STRATEGIES,
    FUNDING_STRATEGY_CATALOG,
    build_ai_discussion_text,
    build_bulk_ai_discussion_text,
    evaluate_funding_strategies,
    parse_strategy_list,
    simulate_bid_for_property,
    simulate_custom_bid_on_history,
)
from app.config import settings
from app.database import (
    ensure_seeded,
    get_or_analyze_property_by_case_no,
    load_all_properties,
    load_property_by_case_no,
    load_winning_history,
    load_winning_record_by_case_no,
    record_new_winning_bid,
    reverify_and_sync_all_stored_properties,
    save_pipeline_results,
)
from app.models import AuctionProperty, WinningBidRecord
from app.scrapers.parsers import normalize_case_no
from app.scrapers.pipeline import (
    build_pipeline_execution_steps,
    run_scraping_and_analysis_pipeline,
)
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.telegram_notifier import (
    bot_poller,
    format_eok_man,
    send_telegram_case_analysis,
    send_telegram_report,
)
from app.weekly_job import run_weekly_scrape_and_notify

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="경매 매력매물(임차인無·소유자거주·권리하자無·미납관리비검증) 필터링 + 6대 부동산 사이트 교차분석 + 낙찰가 추적 및 입찰가 추천 서버",
)

scheduler = AsyncIOScheduler()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["eok_man"] = format_eok_man


class BidSimulationRequest(BaseModel):
    case_no: str
    bid_amount: int


class CaseAnalyzeRequest(BaseModel):
    case_no: str
    send_telegram: bool = False
    force_reanalyze: bool = True
    court_name: Optional[str] = None
    address: Optional[str] = None
    property_type: Optional[str] = None
    exclusive_area_m2: Optional[float] = None
    appraisal_price: Optional[int] = None
    min_bid_price: Optional[int] = None
    occupant_type: Optional[str] = None
    has_tenant: Optional[bool] = None
    has_rights_defect: Optional[bool] = None
    unpaid_mgmt_fee: Optional[int] = None
    is_redev_zone: Optional[bool] = None
    built_year: Optional[int] = None
    strategies: Optional[List[str]] = None
    available_cash: Optional[int] = None


class NewWinningBidInput(BaseModel):
    case_no: str
    court_name: str = "서울서부지방법원"
    property_type: str = "아파트"
    region_name: str
    exclusive_area_m2: float = 59.9
    building_age_years: int = 12
    is_redev_zone: bool = False
    unpaid_mgmt_fee: int = 500_000
    failed_count: int = 1
    appraisal_price: int
    min_bid_price: int
    market_value_at_bid: int
    official_price: int
    winning_bid_price: int
    second_bid_price: int = 0
    bidders_count: int = 8
    sold_date: str = "2026-10-17"


@app.on_event("startup")
async def startup_event() -> None:
    ensure_seeded()
    asyncio.create_task(bot_poller.start())
    if not scheduler.running:
        scheduler.add_job(
            run_weekly_scrape_and_notify,
            CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="weekly_auction_scrape_notify",
            replace_existing=True,
            kwargs={"trigger_source": "apscheduler_weekly"},
        )
        scheduler.start()


@app.get("/api/cron/status")
async def get_cron_status() -> Dict[str, Any]:
    job = scheduler.get_job("weekly_auction_scrape_notify")
    return {
        "scheduler_running": scheduler.running,
        "job_id": job.id if job else None,
        "cron_expression": "0 9 * * 1 (매주 월요일 09:00)",
        "next_run_time": str(job.next_run_time) if job else None,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    ensure_seeded()
    all_props = load_all_properties(attractive_only=False)
    attractive_props = [p for p in all_props if p.is_attractive]
    rejected_props = [p for p in all_props if not p.is_attractive]
    history = load_winning_history()

    avg_market_ratio = (
        round(sum(h.winning_bid_ratio_market for h in history) / len(history), 1)
        if history
        else 86.3
    )
    avg_appraisal_ratio = (
        round(sum(h.winning_bid_ratio_appraisal for h in history) / len(history), 1)
        if history
        else 82.9
    )
    avg_suggested_profit = (
        int(round(sum(h.suggested_optimal_net_profit for h in history) / len(history), -4))
        if history
        else 0
    )
    avg_actual_profit = (
        int(round(sum(h.actual_winner_net_profit for h in history) / len(history), -4))
        if history
        else 0
    )
    avg_gap_1st_2nd = (
        int(round(sum(h.gap_1st_to_2nd_price for h in history) / len(history), -4))
        if history
        else 0
    )
    beat_2nd_count = sum(1 for h in history if h.would_beat_2nd_with_optimal)
    won_1st_opt_count = sum(1 for h in history if h.would_win_with_optimal)
    won_1st_agg_count = sum(1 for h in history if h.would_win_with_aggressive)

    zero_gap_count = sum(
        1 for p in attractive_props if p.official_price.can_zero_gap_invest
    )
    redev_count = sum(1 for p in attractive_props if p.asil.is_redev_zone)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "all_props": all_props,
            "attractive_props": attractive_props,
            "rejected_props": rejected_props,
            "history": history,
            "stats": {
                "total_count": len(all_props),
                "attractive_count": len(attractive_props),
                "rejected_count": len(rejected_props),
                "zero_gap_count": zero_gap_count,
                "redev_count": redev_count,
                "history_count": len(history),
                "avg_market_ratio": avg_market_ratio,
                "avg_appraisal_ratio": avg_appraisal_ratio,
                "avg_suggested_profit": avg_suggested_profit,
                "avg_actual_profit": avg_actual_profit,
                "avg_gap_1st_2nd": avg_gap_1st_2nd,
                "beat_2nd_count": beat_2nd_count,
                "won_1st_opt_count": won_1st_opt_count,
                "won_1st_agg_count": won_1st_agg_count,
            },
        },
    )


@app.get("/api/properties", response_model=List[AuctionProperty])
async def get_properties(
    attractive_only: bool = Query(default=False, description="매력 매물만 필터링 여부"),
) -> List[AuctionProperty]:
    ensure_seeded()
    return load_all_properties(attractive_only=attractive_only)


@app.get("/api/funding-strategies")
async def get_funding_strategies() -> Dict[str, Any]:
    """
    제미나이(Gemini) 상담 export 시 자금 유동성 및 가용 수단 확인을 위해 선택할 수 있는
    자금 조달/대출/레버리지 전략 목록을 반환합니다.
    """
    return {
        "ok": True,
        "default_strategies": DEFAULT_FUNDING_STRATEGIES,
        "strategies": list(FUNDING_STRATEGY_CATALOG.values()),
    }


@app.get("/api/properties/{case_no}/ai-text")
async def get_property_ai_discussion_text(
    case_no: str,
    include_prompt: bool = Query(
        default=True,
        description="제미나이 등 생성형 AI 역할/질문 프롬프트 포함 여부",
    ),
    strategies: Optional[str] = Query(
        default=None,
        description="자금 유동성 확인용 선택 전략 (쉼표 구분: newborn_special,first_time_buyer,auction_balance_loan,jeonse_126_leverage,policy_mortgage,short_term_flipping / 전체: all / 미선택: none)",
    ),
    available_cash: Optional[int] = Query(
        default=None,
        description="보유 가용 현금(자기자본, 원 단위)",
    ),
) -> Dict[str, Any]:
    """
    특정 경매 매물(사건번호)의 상세 내용과 선택한 자금 유동성/대출 전략 시뮬레이션을
    생성형 AI(제미나이, ChatGPT, Claude 등)와 토론하기 좋은 구조화된 텍스트로 추출하여 반환합니다.
    """
    ensure_seeded()
    norm_case = normalize_case_no(case_no)
    if not norm_case:
        raise HTTPException(status_code=400, detail="유효한 사건번호를 입력해주세요.")
    prop = get_or_analyze_property_by_case_no(norm_case)
    liquidity = evaluate_funding_strategies(
        prop, strategies=strategies, available_cash=available_cash
    )
    text = build_ai_discussion_text(
        prop,
        include_prompt=include_prompt,
        strategies=strategies,
        available_cash=available_cash,
    )
    return {
        "ok": True,
        "case_no": prop.case_no,
        "address": prop.address,
        "property_type": prop.property_type,
        "is_attractive": prop.is_attractive,
        "attractiveness_score": prop.attractiveness_score,
        "include_prompt": include_prompt,
        "selected_strategies": liquidity["selected_strategy_ids"],
        "available_cash": available_cash,
        "liquidity_analysis": liquidity,
        "text": text,
    }


@app.get("/api/properties-ai-text")
async def get_bulk_properties_ai_discussion_text(
    attractive_only: bool = Query(
        default=True,
        description="조건 충족 매력 매물만 추출할지 여부 (False면 전체 매물 추출)",
    ),
    include_prompt: bool = Query(
        default=True,
        description="제미나이 등 생성형 AI 비교 토론 프롬프트 포함 여부",
    ),
    strategies: Optional[str] = Query(
        default=None,
        description="자금 유동성 확인용 선택 전략 (쉼표 구분)",
    ),
    available_cash: Optional[int] = Query(
        default=None,
        description="보유 가용 현금(자기자본, 원 단위)",
    ),
) -> Dict[str, Any]:
    """
    추출된 매력 매물 전체(또는 전체 수집 매물)의 상세 내용과 자금 유동성 전략을 한 번에 생성형 AI와
    비교·토론할 수 있도록 구조화된 통합 텍스트로 반환합니다.
    """
    ensure_seeded()
    props = load_all_properties(attractive_only=attractive_only)
    selected_ids = parse_strategy_list(strategies)
    text = build_bulk_ai_discussion_text(
        props,
        include_prompt=include_prompt,
        strategies=selected_ids,
        available_cash=available_cash,
    )
    return {
        "ok": True,
        "count": len(props),
        "attractive_only": attractive_only,
        "include_prompt": include_prompt,
        "selected_strategies": selected_ids,
        "available_cash": available_cash,
        "text": text,
    }


@app.post("/api/analyze-case")
async def analyze_case_endpoint(payload: CaseAnalyzeRequest) -> Dict[str, Any]:
    """
    사건번호(예: '2025타경 2768')를 입력받아 권리관계, 매력도 점수, 6대 사이트 추정 시세 및
    적정 경매 입찰가(보수/적정/공격 3단계)와 AI 토론용 상세 텍스트를 즉석 산출하여 반환하고,
    선택적으로 텔레그램으로도 발송합니다.
    """
    ensure_seeded()
    norm_case = normalize_case_no(payload.case_no)
    if not norm_case:
        raise HTTPException(status_code=400, detail="유효한 사건번호를 입력해주세요. (예: 2025타경 2768)")

    overrides = {
        "court_name": payload.court_name,
        "address": payload.address,
        "property_type": payload.property_type,
        "exclusive_area_m2": payload.exclusive_area_m2,
        "appraisal_price": payload.appraisal_price,
        "min_bid_price": payload.min_bid_price,
        "occupant_type": payload.occupant_type,
        "has_tenant": payload.has_tenant,
        "has_rights_defect": payload.has_rights_defect,
        "unpaid_mgmt_fee": payload.unpaid_mgmt_fee,
        "is_redev_zone": payload.is_redev_zone,
        "built_year": payload.built_year,
    }
    prop = get_or_analyze_property_by_case_no(
        norm_case,
        overrides=overrides,
        force_reanalyze=payload.force_reanalyze,
    )
    tg_result: Optional[Dict[str, Any]] = None
    if payload.send_telegram:
        tg_result = await send_telegram_case_analysis(prop.case_no)

    liquidity = evaluate_funding_strategies(
        prop,
        strategies=payload.strategies,
        available_cash=payload.available_cash,
    )

    return {
        "ok": True,
        "case_no": prop.case_no,
        "pipeline_steps": build_pipeline_execution_steps(prop),
        "property": prop.model_dump(),
        "liquidity_analysis": liquidity,
        "ai_discussion_text": build_ai_discussion_text(
            prop,
            include_prompt=True,
            strategies=payload.strategies,
            available_cash=payload.available_cash,
        ),
        "telegram": tg_result,
    }


@app.get("/api/history", response_model=List[WinningBidRecord])
async def get_winning_history() -> List[WinningBidRecord]:
    ensure_seeded()
    return load_winning_history()


@app.post("/api/scrape")
async def trigger_scrape_and_analyze(send_telegram: bool = False) -> Dict[str, Any]:
    props, history = run_scraping_and_analysis_pipeline()
    save_pipeline_results(props, history)
    all_synced = reverify_and_sync_all_stored_properties(enable_network=True)
    attractive = [p for p in all_synced if p.is_attractive]

    tg_result: Optional[Dict[str, Any]] = None
    if send_telegram:
        tg_result = await send_telegram_report(attractive, history)

    return {
        "ok": True,
        "total_scraped": len(all_synced),
        "attractive_count": len(attractive),
        "history_count": len(history),
        "telegram": tg_result,
    }


@app.post("/api/telegram/send")
async def trigger_telegram_notification(request: Request) -> Dict[str, Any]:
    ensure_seeded()
    attractive = load_all_properties(attractive_only=True)
    history = load_winning_history()
    base_url = str(request.base_url).rstrip("/")
    result = await send_telegram_report(attractive, history, dashboard_url=base_url)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "전송 실패"))
    return result


@app.post("/api/simulate-bid")
async def simulate_custom_bid(payload: BidSimulationRequest) -> Dict[str, Any]:
    ensure_seeded()
    norm_case = normalize_case_no(payload.case_no)
    prop = load_property_by_case_no(norm_case)
    if prop:
        return simulate_bid_for_property(prop, payload.bid_amount)
    hist_rec = load_winning_record_by_case_no(norm_case)
    if hist_rec:
        return simulate_custom_bid_on_history(hist_rec, payload.bid_amount)
    prop = get_or_analyze_property_by_case_no(norm_case)
    if prop:
        return simulate_bid_for_property(prop, payload.bid_amount)
    raise HTTPException(status_code=404, detail="해당 사건번호 매물을 찾을 수 없습니다.")


@app.post("/api/history/simulate")
async def simulate_historical_bid(payload: BidSimulationRequest) -> Dict[str, Any]:
    """과거 낙찰 매물에 대해 제시 입찰가 또는 사용자 희망가로 입찰 시 이득(순수익) 및 2등과의 차이 시뮬레이션"""
    ensure_seeded()
    history = load_winning_history()
    target = next((h for h in history if h.case_no == payload.case_no), None)
    if not target:
        raise HTTPException(status_code=404, detail="해당 사건번호 과거 낙찰 기록을 찾을 수 없습니다.")
    return simulate_custom_bid_on_history(target, payload.bid_amount, history)


@app.post("/api/history/record")
async def add_winning_bid_record(payload: NewWinningBidInput) -> Dict[str, Any]:
    ratio_appraisal = round((payload.winning_bid_price / payload.appraisal_price) * 100, 1)
    ratio_market = round((payload.winning_bid_price / payload.market_value_at_bid) * 100, 1)

    record = WinningBidRecord(
        case_no=payload.case_no,
        court_name=payload.court_name,
        property_type=payload.property_type,
        region_name=payload.region_name,
        exclusive_area_m2=payload.exclusive_area_m2,
        building_age_years=payload.building_age_years,
        is_redev_zone=payload.is_redev_zone,
        has_tenant=False,
        occupant_type="소유자",
        has_rights_defect=False,
        unpaid_mgmt_fee=payload.unpaid_mgmt_fee,
        failed_count=payload.failed_count,
        appraisal_price=payload.appraisal_price,
        min_bid_price=payload.min_bid_price,
        market_value_at_bid=payload.market_value_at_bid,
        official_price=payload.official_price,
        winning_bid_price=payload.winning_bid_price,
        second_bid_price=payload.second_bid_price,
        winning_bid_ratio_appraisal=ratio_appraisal,
        winning_bid_ratio_market=ratio_market,
        bidders_count=payload.bidders_count,
        sold_date=payload.sold_date,
    )
    updated_props = record_new_winning_bid(record)
    saved_rec = load_winning_record_by_case_no(record.case_no)
    return {
        "ok": True,
        "recorded_case_no": record.case_no,
        "winning_bid_ratio_appraisal": ratio_appraisal,
        "winning_bid_ratio_market": ratio_market,
        "suggested_optimal_bid": saved_rec.suggested_optimal_bid if saved_rec else 0,
        "suggested_optimal_net_profit": saved_rec.suggested_optimal_net_profit if saved_rec else 0,
        "actual_winner_net_profit": saved_rec.actual_winner_net_profit if saved_rec else 0,
        "gap_1st_to_2nd_price": saved_rec.gap_1st_to_2nd_price if saved_rec else 0,
        "recalculated_properties": len(updated_props),
    }


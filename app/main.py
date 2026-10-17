from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.analyzer import simulate_bid_for_property
from app.config import settings
from app.database import (
    ensure_seeded,
    load_all_properties,
    load_property_by_case_no,
    load_winning_history,
    record_new_winning_bid,
    save_pipeline_results,
)
from app.models import AuctionProperty, WinningBidRecord
from app.scrapers.pipeline import run_scraping_and_analysis_pipeline
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.telegram_notifier import bot_poller, format_eok_man, send_telegram_report
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
            },
        },
    )


@app.get("/api/properties", response_model=List[AuctionProperty])
async def get_properties(
    attractive_only: bool = Query(default=False, description="매력 매물만 필터링 여부"),
) -> List[AuctionProperty]:
    ensure_seeded()
    return load_all_properties(attractive_only=attractive_only)


@app.get("/api/history", response_model=List[WinningBidRecord])
async def get_winning_history() -> List[WinningBidRecord]:
    ensure_seeded()
    return load_winning_history()


@app.post("/api/scrape")
async def trigger_scrape_and_analyze(send_telegram: bool = False) -> Dict[str, Any]:
    props, history = run_scraping_and_analysis_pipeline()
    save_pipeline_results(props, history)
    attractive = [p for p in props if p.is_attractive]

    tg_result: Optional[Dict[str, Any]] = None
    if send_telegram:
        tg_result = await send_telegram_report(attractive, history)

    return {
        "ok": True,
        "total_scraped": len(props),
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
    prop = load_property_by_case_no(payload.case_no)
    if not prop:
        raise HTTPException(status_code=404, detail="해당 사건번호 매물을 찾을 수 없습니다.")
    return simulate_bid_for_property(prop, payload.bid_amount)


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
        winning_bid_ratio_appraisal=ratio_appraisal,
        winning_bid_ratio_market=ratio_market,
        bidders_count=payload.bidders_count,
        sold_date=payload.sold_date,
    )
    updated_props = record_new_winning_bid(record)
    return {
        "ok": True,
        "recorded_case_no": record.case_no,
        "winning_bid_ratio_appraisal": ratio_appraisal,
        "winning_bid_ratio_market": ratio_market,
        "recalculated_properties": len(updated_props),
    }

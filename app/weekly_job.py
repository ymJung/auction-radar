import asyncio
from datetime import datetime, timezone
from pathlib import Path

from app.database import reverify_and_sync_all_stored_properties, save_pipeline_results
from app.scrapers.pipeline import run_scraping_and_analysis_pipeline
from app.telegram_notifier import send_telegram_report

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "weekly_cron.log"


async def run_weekly_scrape_and_notify(trigger_source: str = "cron") -> dict:
    """
    주 1회(또는 스케줄러 호출 시) 6대 부동산 사이트 재스크래핑·권리분석·물건종류 재검증·입찰가 추천을 수행하고
    TELEGRAM_BOT_2로 대화형 추천 리포트를 발송합니다.
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    props, history = run_scraping_and_analysis_pipeline()
    save_pipeline_results(props, history)
    all_synced = reverify_and_sync_all_stored_properties(enable_network=True)
    attractive = [p for p in all_synced if p.is_attractive]

    tg_res = await send_telegram_report(attractive, history)

    log_line = (
        f"[{now_str}] source={trigger_source} | scraped={len(props)} | "
        f"attractive={len(attractive)} | history={len(history)} | "
        f"telegram_ok={tg_res.get('ok')} | msg_ids={tg_res.get('message_ids')}\n"
    )
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(log_line)

    return {
        "timestamp": now_str,
        "trigger_source": trigger_source,
        "scraped_count": len(props),
        "attractive_count": len(attractive),
        "telegram": tg_res,
    }


def main() -> None:
    res = asyncio.run(run_weekly_scrape_and_notify(trigger_source="system_crontab"))
    print(res)


if __name__ == "__main__":
    main()

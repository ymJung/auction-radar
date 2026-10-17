import json
import sqlite3
from pathlib import Path
from typing import List, Optional
from app.analyzer import evaluate_and_recommend
from app.config import settings
from app.models import AuctionProperty, WinningBidRecord
from app.scrapers.pipeline import run_scraping_and_analysis_pipeline


def get_connection() -> sqlite3.Connection:
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auction_properties (
                case_no TEXT PRIMARY KEY,
                property_type TEXT NOT NULL,
                is_attractive INTEGER NOT NULL,
                attractiveness_score INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS winning_bid_history (
                case_no TEXT PRIMARY KEY,
                property_type TEXT NOT NULL,
                sold_date TEXT NOT NULL,
                winning_bid_price INTEGER NOT NULL,
                winning_bid_ratio_appraisal REAL NOT NULL,
                winning_bid_ratio_market REAL NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_pipeline_results(
    properties: List[AuctionProperty],
    history: List[WinningBidRecord],
) -> None:
    init_db()
    with get_connection() as conn:
        for h in history:
            conn.execute(
                """
                INSERT INTO winning_bid_history (
                    case_no, property_type, sold_date, winning_bid_price,
                    winning_bid_ratio_appraisal, winning_bid_ratio_market, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_no) DO UPDATE SET
                    sold_date = excluded.sold_date,
                    winning_bid_price = excluded.winning_bid_price,
                    winning_bid_ratio_appraisal = excluded.winning_bid_ratio_appraisal,
                    winning_bid_ratio_market = excluded.winning_bid_ratio_market,
                    payload_json = excluded.payload_json
                """,
                (
                    h.case_no,
                    h.property_type,
                    h.sold_date,
                    h.winning_bid_price,
                    h.winning_bid_ratio_appraisal,
                    h.winning_bid_ratio_market,
                    h.model_dump_json(),
                ),
            )

        for p in properties:
            conn.execute(
                """
                INSERT INTO auction_properties (
                    case_no, property_type, is_attractive, attractiveness_score, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_no) DO UPDATE SET
                    property_type = excluded.property_type,
                    is_attractive = excluded.is_attractive,
                    attractiveness_score = excluded.attractiveness_score,
                    payload_json = excluded.payload_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    p.case_no,
                    p.property_type,
                    1 if p.is_attractive else 0,
                    p.attractiveness_score,
                    p.model_dump_json(),
                ),
            )
        conn.commit()


def load_all_properties(attractive_only: bool = False) -> List[AuctionProperty]:
    init_db()
    with get_connection() as conn:
        if attractive_only:
            rows = conn.execute(
                "SELECT payload_json FROM auction_properties WHERE is_attractive = 1 ORDER BY attractiveness_score DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload_json FROM auction_properties ORDER BY is_attractive DESC, attractiveness_score DESC"
            ).fetchall()
    return [AuctionProperty.model_validate_json(r["payload_json"]) for r in rows]


def load_property_by_case_no(case_no: str) -> Optional[AuctionProperty]:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT payload_json FROM auction_properties WHERE case_no = ?",
            (case_no,),
        ).fetchone()
    if not row:
        return None
    return AuctionProperty.model_validate_json(row["payload_json"])


def load_winning_history() -> List[WinningBidRecord]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT payload_json FROM winning_bid_history ORDER BY sold_date DESC"
        ).fetchall()
    return [WinningBidRecord.model_validate_json(r["payload_json"]) for r in rows]


def record_new_winning_bid(record: WinningBidRecord) -> List[AuctionProperty]:
    """
    새로운 낙찰 결과를 DB에 추적 기록하고, 전체 진행중 매물의 추천 입찰가를 최신 낙찰가율 트렌드로 재계산합니다.
    """
    init_db()
    history = load_winning_history()
    history = [h for h in history if h.case_no != record.case_no]
    history.insert(0, record)

    props = load_all_properties(attractive_only=False)
    updated_props: List[AuctionProperty] = []
    for p in props:
        if p.case_no == record.case_no:
            p.status = "낙찰"
            p.winning_bid_price = record.winning_bid_price
            p.winning_bid_ratio = record.winning_bid_ratio_appraisal
            p.bidders_count = record.bidders_count
        p = evaluate_and_recommend(p, history)
        updated_props.append(p)

    save_pipeline_results(updated_props, history)
    return updated_props


def ensure_seeded() -> None:
    init_db()
    props = load_all_properties(attractive_only=False)
    if not props:
        props, history = run_scraping_and_analysis_pipeline()
        save_pipeline_results(props, history)

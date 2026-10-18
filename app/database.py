from contextlib import contextmanager
from typing import Any, Generator, List, Optional
import pymysql
from pymysql.cursors import DictCursor

from app.analyzer import evaluate_and_recommend
from app.config import settings
from app.models import AuctionProperty, WinningBidRecord
from app.scrapers.pipeline import run_scraping_and_analysis_pipeline


@contextmanager
def get_connection() -> Generator[pymysql.connections.Connection, None, None]:
    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auction_properties (
                    case_no VARCHAR(64) PRIMARY KEY,
                    property_type VARCHAR(64) NOT NULL,
                    is_attractive TINYINT(1) NOT NULL,
                    attractiveness_score INT NOT NULL,
                    payload_json LONGTEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS winning_bid_history (
                    case_no VARCHAR(64) PRIMARY KEY,
                    property_type VARCHAR(64) NOT NULL,
                    sold_date VARCHAR(32) NOT NULL,
                    winning_bid_price BIGINT NOT NULL,
                    winning_bid_ratio_appraisal DOUBLE NOT NULL,
                    winning_bid_ratio_market DOUBLE NOT NULL,
                    payload_json LONGTEXT NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        conn.commit()


def save_pipeline_results(
    properties: List[AuctionProperty],
    history: List[WinningBidRecord],
) -> None:
    init_db()
    with get_connection() as conn:
        with conn.cursor() as cur:
            for h in history:
                cur.execute(
                    """
                    INSERT INTO winning_bid_history (
                        case_no, property_type, sold_date, winning_bid_price,
                        winning_bid_ratio_appraisal, winning_bid_ratio_market, payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        sold_date = VALUES(sold_date),
                        winning_bid_price = VALUES(winning_bid_price),
                        winning_bid_ratio_appraisal = VALUES(winning_bid_ratio_appraisal),
                        winning_bid_ratio_market = VALUES(winning_bid_ratio_market),
                        payload_json = VALUES(payload_json)
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
                cur.execute(
                    """
                    INSERT INTO auction_properties (
                        case_no, property_type, is_attractive, attractiveness_score, payload_json
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        property_type = VALUES(property_type),
                        is_attractive = VALUES(is_attractive),
                        attractiveness_score = VALUES(attractiveness_score),
                        payload_json = VALUES(payload_json),
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
        with conn.cursor() as cur:
            if attractive_only:
                cur.execute(
                    "SELECT payload_json FROM auction_properties WHERE is_attractive = 1 ORDER BY attractiveness_score DESC"
                )
            else:
                cur.execute(
                    "SELECT payload_json FROM auction_properties ORDER BY is_attractive DESC, attractiveness_score DESC"
                )
            rows = cur.fetchall()
    return [AuctionProperty.model_validate_json(r["payload_json"]) for r in rows]


def load_property_by_case_no(case_no: str) -> Optional[AuctionProperty]:
    init_db()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM auction_properties WHERE case_no = %s",
                (case_no,),
            )
            row: Optional[dict[str, Any]] = cur.fetchone()
    if not row:
        return None
    return AuctionProperty.model_validate_json(row["payload_json"])


def load_winning_history() -> List[WinningBidRecord]:
    init_db()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM winning_bid_history ORDER BY sold_date DESC"
            )
            rows = cur.fetchall()
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

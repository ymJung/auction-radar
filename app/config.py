import os
from pathlib import Path
from dotenv import load_dotenv

# Load ~/.env first, then project .env if present
HOME_ENV_PATH = Path.home() / ".env"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_PATH = PROJECT_ROOT / ".env"

if HOME_ENV_PATH.exists():
    load_dotenv(HOME_ENV_PATH, override=False)
if LOCAL_ENV_PATH.exists():
    load_dotenv(LOCAL_ENV_PATH, override=True)


class Settings:
    PROJECT_NAME: str = "AuctionRadar (경매 매력물건 발굴 & 입찰가 추천 서버)"
    VERSION: str = "1.0.0"
    DB_PATH: Path = PROJECT_ROOT / "data" / "auction_radar.db"

    # Docker MySQL Configuration
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "127.0.0.1").strip()
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "devuser").strip()
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "devpass123!").strip()
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "auction_radar").strip()

    # Telegram Configuration from ~/.env
    TELEGRAM_USER_ID: str = os.getenv("TELEGRAM_USER_ID", "").strip()
    TELEGRAM_BOT_1: str = os.getenv("TELEGRAM_BOT_1", "").strip().replace(" ", "")
    TELEGRAM_BOT_2: str = os.getenv("TELEGRAM_BOT_2", "").strip().replace(" ", "")
    TELEGRAM_BOT_3: str = os.getenv("TELEGRAM_BOT_3", "").strip().replace(" ", "")

    # Optional Open API Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    MOLIT_API_KEY: str = os.getenv("MOLIT_API_KEY", "").strip()

    # Core Auction Policy Constants
    # ⑤ 공시가격알리미 - 전세보증보험 한도 (공시가 × 126%, 10월 기준)
    JEONSE_INSURANCE_RATIO: float = 1.26

    # 미납 관리비: 통상 공용관리비 3년치 인수 리스크 비중 (전체 미납액 중 공용부분 비율 약 75% 가정)
    COMMON_MGMT_FEE_ASSUMPTION_RATIO: float = 0.75
    # 매력 매물 필터링 시 허용 가능한 최대 미납관리비 한도 (감정가의 3% 또는 1,000만원 이하)
    MAX_ACCEPTABLE_UNPAID_MGMT_FEE: int = 10_000_000

    # Server Port
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    @property
    def active_telegram_token(self) -> str:
        """Return TELEGRAM_BOT_2 as primary token from ~/.env."""
        load_dotenv(HOME_ENV_PATH, override=True)
        bot2 = os.getenv("TELEGRAM_BOT_2", "").strip().replace(" ", "")
        if bot2 and ":" in bot2:
            return bot2
        for token in (self.TELEGRAM_BOT_1, self.TELEGRAM_BOT_3):
            if token and ":" in token:
                return token
        return ""


settings = Settings()

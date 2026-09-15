"""Application configuration; environment variables take precedence over .env."""

import os
import math
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

Region = Literal["DE", "IE", "FR", "PL"]
REGIONS = ("DE", "IE", "FR", "PL")
ENTSOE_API_KEY = os.getenv("ENTSOE_API_KEY", "")
ELECTRICITY_MAPS_API_KEY = os.getenv("ELECTRICITY_MAPS_API_KEY", "")
USE_LIVE_API = os.getenv("USE_LIVE_API", "false").lower() == "true"
OPENWHISK_REAL = os.getenv("OPENWHISK_REAL", "false").lower() == "true"
OPENWHISK_HOST = os.getenv("OPENWHISK_HOST", "http://localhost:3233")
OPENWHISK_AUTH = os.getenv("OPENWHISK_AUTH", "")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "routing.db")))
ENERGY_KWH_PER_REQUEST = float(os.getenv("ENERGY_KWH_PER_REQUEST", "0.001"))
if not math.isfinite(ENERGY_KWH_PER_REQUEST) or ENERGY_KWH_PER_REQUEST <= 0:
    raise ValueError("ENERGY_KWH_PER_REQUEST must be finite and positive")

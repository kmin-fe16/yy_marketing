"""네이버 검색광고 API — 캠페인 데이터 조회."""
import os
import re
import hmac
import hashlib
import base64
import time
import requests
from datetime import date as date_cls
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("NAVER_AD_API_KEY", "")
SECRET = os.getenv("NAVER_AD_SECRET", "")
CUSTOMER_ID = os.getenv("NAVER_AD_CUSTOMER_ID", "")
BASE_URL = "https://api.naver.com"


def _sign(timestamp: str, method: str, path: str) -> str:
    message = f"{timestamp}.{method}.{path}"
    sig = hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig).decode()


def _headers(method: str, path: str) -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "X-Timestamp": ts,
        "X-API-KEY": API_KEY,
        "X-Customer": CUSTOMER_ID,
        "X-Signature": _sign(ts, method, path),
    }


def get_campaigns(today: date_cls = None) -> list:
    """네이버 검색광고 캠페인 조회. 자격증명 없으면 빈 리스트."""
    if not API_KEY or not SECRET or not CUSTOMER_ID:
        return []
    if today is None:
        today = date_cls.today()

    path = "/ncc/campaigns"
    try:
        resp = requests.get(
            f"{BASE_URL}{path}",
            headers=_headers("GET", path),
            timeout=15,
        )
        resp.raise_for_status()
        campaigns = resp.json()
    except Exception as e:
        print(f"[네이버] 캠페인 조회 실패: {e}")
        return []

    result = []
    date_from = "2026-01-01"
    date_to = date_cls.today().isoformat().replace("-", "")

    for c in campaigns:
        event_date = _parse_date(c.get("name", ""))
        if not event_date or event_date < today:
            continue

        spend, impressions, clicks, ctr = 0, 0, 0, 0.0
        try:
            stat_path = f"/stats?ids={c['nccCampaignId']}&dateType=date&dateFrom=20260101&dateTo={date_to}&timeRange=allDays"
            stat_resp = requests.get(
                f"{BASE_URL}{stat_path}",
                headers=_headers("GET", stat_path),
                timeout=10,
            )
            if stat_resp.ok:
                rows = stat_resp.json().get("data", [{}])
                if rows:
                    s = rows[0]
                    spend = float(s.get("cost", 0))
                    impressions = int(s.get("impCnt", 0))
                    clicks = int(s.get("clkCnt", 0))
                    ctr = float(s.get("ctr", 0))
        except Exception:
            pass

        result.append({
            "id": c.get("nccCampaignId", ""),
            "name": c.get("name", ""),
            "status": "ACTIVE" if c.get("userLock") is False else "PAUSED",
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "reach": 0,
            "platform": "naver",
            "created": c.get("regTm", "")[:10],
            "event_date": event_date.isoformat(),
        })
    return result


def _parse_date(name: str):
    m = re.match(r"26(\d{2})(\d{2})", name.strip())
    if m:
        try:
            return date_cls(2026, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None

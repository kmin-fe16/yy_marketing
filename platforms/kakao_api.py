"""카카오 Moment API — 캠페인 데이터 조회."""
import os
import re
import requests
from datetime import date as date_cls
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("KAKAO_AD_ACCESS_TOKEN", "")
ACCOUNT_ID = os.getenv("KAKAO_AD_ACCOUNT_ID", "")
BASE_URL = "https://apis.moment.kakao.com/openapi/v4"


def get_campaigns(today: date_cls = None) -> list:
    """카카오 Moment 캠페인 조회. 자격증명 없으면 빈 리스트."""
    if not TOKEN or not ACCOUNT_ID:
        return []
    if today is None:
        today = date_cls.today()

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "adAccountId": ACCOUNT_ID,
    }

    try:
        resp = requests.get(f"{BASE_URL}/campaigns", headers=headers, timeout=15)
        resp.raise_for_status()
        campaigns = resp.json().get("content", [])
    except Exception as e:
        print(f"[카카오] 캠페인 조회 실패: {e}")
        return []

    result = []
    date_from = "2026-01-01"
    date_to = date_cls.today().isoformat()

    for c in campaigns:
        event_date = _parse_date(c.get("name", ""))
        if not event_date or event_date < today:
            continue
        # 성과 조회
        spend, impressions, clicks, ctr = 0, 0, 0, 0.0
        try:
            stat_resp = requests.get(
                f"{BASE_URL}/campaigns/stat",
                headers=headers,
                params={"campaignId": c["id"], "dateFrom": date_from, "dateTo": date_to},
                timeout=10,
            )
            if stat_resp.ok:
                s = stat_resp.json()
                spend = float(s.get("cost", 0))
                impressions = int(s.get("impression", 0))
                clicks = int(s.get("click", 0))
                ctr = round(clicks / impressions * 100, 2) if impressions else 0.0
        except Exception:
            pass

        result.append({
            "id": str(c["id"]),
            "name": c.get("name", ""),
            "status": "ACTIVE" if c.get("config", {}).get("status") == "ON" else "PAUSED",
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "reach": 0,
            "platform": "kakao",
            "created": c.get("createdDate", "")[:10],
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

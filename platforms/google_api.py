"""구글 Ads API — 캠페인 데이터 조회."""
import os
import re
from datetime import date as date_cls
from dotenv import load_dotenv

load_dotenv()

DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")
REFRESH_TOKEN = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "")


def get_campaigns(today: date_cls = None) -> list:
    """구글 Ads 캠페인 조회. 자격증명 없으면 빈 리스트."""
    if not DEVELOPER_TOKEN or not CUSTOMER_ID or not REFRESH_TOKEN:
        return []
    if today is None:
        today = date_cls.today()

    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        print("[구글] google-ads 패키지 없음. pip install google-ads")
        return []

    try:
        client = GoogleAdsClient.load_from_dict({
            "developer_token": DEVELOPER_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "login_customer_id": CUSTOMER_ID,
        })
        ga_service = client.get_service("GoogleAdsService")
        query = """
            SELECT
                campaign.id, campaign.name, campaign.status,
                metrics.cost_micros, metrics.impressions,
                metrics.clicks, metrics.ctr
            FROM campaign
            WHERE segments.date BETWEEN '2026-01-01' AND '2026-12-31'
              AND campaign.status IN ('ENABLED', 'PAUSED')
        """
        response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
    except Exception as e:
        print(f"[구글] 캠페인 조회 실패: {e}")
        return []

    result = []
    totals = {}
    for row in response:
        cid = str(row.campaign.id)
        if cid not in totals:
            totals[cid] = {
                "name": row.campaign.name,
                "status": row.campaign.status.name,
                "spend": 0, "impressions": 0, "clicks": 0,
            }
        totals[cid]["spend"] += row.metrics.cost_micros / 1_000_000
        totals[cid]["impressions"] += row.metrics.impressions
        totals[cid]["clicks"] += row.metrics.clicks

    for cid, data in totals.items():
        event_date = _parse_date(data["name"])
        if not event_date or event_date < today:
            continue
        imp = data["impressions"]
        ctr = round(data["clicks"] / imp * 100, 2) if imp else 0.0
        result.append({
            "id": cid,
            "name": data["name"],
            "status": "ACTIVE" if data["status"] == "ENABLED" else "PAUSED",
            "spend": round(data["spend"], 2),
            "impressions": imp,
            "clicks": data["clicks"],
            "ctr": ctr,
            "reach": 0,
            "platform": "google",
            "created": "",
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

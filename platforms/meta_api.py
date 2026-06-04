"""Meta (Facebook) Ads API — 캠페인 데이터 조회."""
import os
import re
import requests
from datetime import date as date_cls
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("META_ACCESS_TOKEN", os.getenv("ACCESS_TOKEN", ""))
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "act_810493558680773")
API_VERSION = os.getenv("META_API_VERSION", "v20.0")
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

# generate_dashboard.py에서 직접 사용하는 토큰 (하드코딩 fallback)
HARDCODED_TOKEN = "EAAcS3syXjtcBRqFui6iZBybqqcUYJmjQQCZCSy9zFUY3KN0JRtivnEdRmnmbchMKr4O3j03FIRvVqmZCRtklJ5ijGODGlIZBteZCoGTyf74Pkh8GJ0SXlGIW65r2QW0Ifs6njWqvIjqwU1DfJ6lasdxkLnbeaIuOvo5cVrDZAkufu47dOs8ZC5TZBk1svQnZCqMg2cdOzgYX2C19d4ZBtZAef8j"


def _token():
    return TOKEN or HARDCODED_TOKEN


def get_campaigns(today: date_cls = None) -> list:
    """오늘 이후 행사의 Meta 캠페인(ACTIVE+PAUSED) 조회. 정규화된 리스트 반환."""
    if today is None:
        today = date_cls.today()

    campaigns = []
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/campaigns"
    params = {
        "fields": (
            "id,name,status,objective,created_time,"
            "insights.time_range({'since':'2026-01-01','until':'2026-12-31'})"
            "{impressions,clicks,spend,reach,ctr,cpc}"
        ),
        "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE","PAUSED"]}]',
        "access_token": _token(),
        "limit": 200,
    }
    while url:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        campaigns.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}

    result = []
    for c in campaigns:
        event_date = _parse_date(c["name"])
        if not event_date or event_date < today:
            continue
        raw = c.get("insights", {}).get("data", [{}])[0]
        result.append({
            "id": c["id"],
            "name": c["name"],
            "status": c["status"],
            "spend": float(raw.get("spend", 0)),
            "impressions": int(raw.get("impressions", 0)),
            "clicks": int(raw.get("clicks", 0)),
            "ctr": float(raw.get("ctr", 0)),
            "reach": int(raw.get("reach", 0)),
            "cpc": float(raw.get("cpc", 0)),
            "platform": "meta",
            "created": c.get("created_time", "")[:10],
            "event_date": event_date.isoformat(),
        })
    return result


def get_ads(campaign_ids: set) -> list:
    """캠페인 ID 목록 기준 광고(에셋) 조회."""
    if not campaign_ids:
        return []
    ads = []
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/ads"
    params = {
        "fields": (
            "id,name,status,campaign_id,"
            "creative{thumbnail_url},"
            "insights.time_range({'since':'2026-01-01','until':'2026-12-31'})"
            "{ctr,cpm,spend,impressions,clicks}"
        ),
        "filtering": '[{"field":"campaign.effective_status","operator":"IN","value":["ACTIVE","PAUSED"]}]',
        "access_token": _token(),
        "limit": 500,
    }
    while url:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        ads.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
    return [a for a in ads if a.get("campaign_id") in campaign_ids]


def _parse_date(name: str):
    m = re.match(r"26(\d{2})(\d{2})", name.strip())
    if m:
        try:
            return date_cls(2026, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None

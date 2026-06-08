"""Notion DB '대기' 행사 → Meta 캠페인 자동 생성.

캠페인 2개 생성:
  - YYMMDD 지역 공연명 N차        (트래픽, 35,000원/일)
  - YYMMDD 지역 공연명 N차 잠재   (잠재, 20,000원/일)
각 캠페인 아래 광고세트 1개 + 에셋-1/2/3 광고 3개.
완료 시 Notion 상태 → '업로드완료'.
"""
import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from notion_client_helper import parse_campaign, update_campaign
from telegram_bot import send_message

load_dotenv()

TOKEN      = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT = os.getenv("META_AD_ACCOUNT_ID", "act_810493558680773")
API        = f"https://graph.facebook.com/{os.getenv('META_API_VERSION', 'v20.0')}"
NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
CAMPAIGN_DB_ID = os.getenv("CAMPAIGN_NOTION_DB_ID", os.getenv("NOTION_DB_ID"))

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

BUDGET_TRAFFIC  = 35_000   # 트래픽 일예산 (원)
BUDGET_LATENT   = 20_000   # 잠재 일예산 (원)

_page_id_cache = None


# ── Notion 조회 ──────────────────────────────────────────────────────

def query_pending() -> list:
    """CAMPAIGN_NOTION_DB_ID에서 상태='대기' 페이지 전체 조회."""
    pages, cursor = [], None
    while True:
        body = {"filter": {"property": "상태", "select": {"equals": "대기"}}}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{CAMPAIGN_DB_ID}/query",
            headers=NOTION_HEADERS, json=body, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return pages


# ── Google Drive URL → Meta 이미지 해시 ──────────────────────────────

def gdrive_to_image_hash(drive_url: str) -> str:
    """Google Drive 공유 URL에서 이미지를 다운로드해 Meta adimages에 업로드."""
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', drive_url) \
     or re.search(r'[?&]id=([a-zA-Z0-9_-]+)', drive_url)
    if not m:
        raise ValueError(f"Google Drive URL 파싱 실패: {drive_url}")
    file_id = m.group(1)

    dl_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    img_resp = requests.get(dl_url, timeout=30, allow_redirects=True)
    img_resp.raise_for_status()

    files = {"filename": (f"{file_id}.jpg", img_resp.content, "image/jpeg")}
    upload = requests.post(
        f"{API}/{AD_ACCOUNT}/adimages",
        params={"access_token": TOKEN},
        files=files,
        timeout=30,
    )
    upload.raise_for_status()
    images = upload.json().get("images", {})
    if not images:
        raise RuntimeError(f"이미지 업로드 실패: {upload.json()}")
    return list(images.values())[0]["hash"]


# ── Meta API 헬퍼 ────────────────────────────────────────────────────

FB_PAGE_ID = os.getenv("META_FB_PAGE_ID", "952888584569714")
IG_USER_ID = os.getenv("META_IG_USER_ID", "17841478746782671")


def _get_page_id() -> str:
    global _page_id_cache
    if _page_id_cache:
        return _page_id_cache
    resp = requests.get(
        f"{API}/{AD_ACCOUNT}/promote_pages",
        params={"access_token": TOKEN, "fields": "id"},
        timeout=10,
    )
    if resp.ok:
        data = resp.json().get("data", [])
        if data:
            _page_id_cache = data[0]["id"]
            return _page_id_cache
    _page_id_cache = FB_PAGE_ID
    return FB_PAGE_ID


def create_campaign(name: str) -> str:
    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/campaigns",
        params={"access_token": TOKEN},
        json={
            "name": name,
            "objective": "OUTCOME_TRAFFIC",
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_adset(campaign_id: str, name: str, daily_budget: int, info: dict) -> str:
    targeting = {
        "age_min": 32,
        "age_max": 62,
        "genders": [2],                          # 여성
        "geo_locations": {"countries": ["KR"]},
        "publisher_platforms": ["facebook"],
        "facebook_positions": ["feed"],
        "targeting_relaxation_types": {"lookalike": 0, "custom_audience": 0},
        "targeting_automation": {"advantage_audience": 0},
    }

    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adsets",
        params={"access_token": TOKEN},
        json={
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": daily_budget,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LANDING_PAGE_VIEWS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": targeting,
            "status": "PAUSED",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_ad(adset_id: str, camp_name: str, n: int, image_hash: str, info: dict) -> str:
    ad_name = f"{camp_name}-{n}"
    label = ["A", "B", "C"][n - 1]
    headline = info.get(f"광고제목{label}") or ""
    body = info.get(f"광고본문{label}") or ""
    creative_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adcreatives",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "object_story_spec": {
                "page_id": _get_page_id(),
                "instagram_user_id": IG_USER_ID,
                "link_data": {
                    "image_hash": image_hash,
                    "link": info["랜딩URL"],
                    "message": body,
                    "name": headline,
                    "call_to_action": {
                        "type": "APPLY_NOW",
                    },
                },
            },
        },
        timeout=15,
    )
    if not creative_resp.ok:
        raise RuntimeError(f"adcreative 실패: {creative_resp.json()}")
    creative_id = creative_resp.json()["id"]

    ad_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/ads",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
        timeout=15,
    )
    ad_resp.raise_for_status()
    return ad_resp.json()["id"]


# ── 캠페인명 생성 ────────────────────────────────────────────────────

def build_camp_name(info: dict, suffix: str = "") -> str:
    d = datetime.fromisoformat(info["공연일"])
    yymmdd = d.strftime("%y%m%d")
    return f"{yymmdd} {info['지역']} {info['공연명']} {info['차수']}{suffix}"


# ── 행사 1개 처리 ────────────────────────────────────────────────────

def process(page: dict):
    info = parse_campaign(page)
    name = info["공연명"]
    print(f"\n  처리 중: {name}")

    camp_name = build_camp_name(info)

    # 이미지 업로드
    asset_urls = [u for u in [info["에셋A"], info["에셋B"], info["에셋C"]] if u]
    if not asset_urls:
        print(f"  ⚠️  에셋 URL 없음 — 건너뜀: {name}")
        return

    print(f"    이미지 업로드 중 ({len(asset_urls)}개)...")
    hashes = []
    for url in asset_urls:
        h = gdrive_to_image_hash(url)
        hashes.append(h)
        print(f"    ✓ 업로드 완료: {url[:60]}...")

    # 캠페인1: 트래픽
    print(f"    캠페인1 생성: {camp_name}")
    cid1   = create_campaign(camp_name)
    asid1  = create_adset(cid1, camp_name, BUDGET_TRAFFIC, info)
    for n, h in enumerate(hashes, 1):
        create_ad(asid1, camp_name, n, h, info)
    print(f"    → 캠페인ID: {cid1}, 에셋 {len(hashes)}개")

    # 노션 업데이트
    update_campaign(info["page_id"], {
        "상태": "업로드완료",
        "Meta 캠페인ID": cid1,
        "Meta 광고세트ID": asid1,
    })

    # 텔레그램 알림
    send_message(
        f"🎭 <b>[{camp_name}] 캠페인 생성 완료</b>\n\n"
        f"📍 지역: {info['지역']}\n"
        f"📅 공연일: {info['공연일']}\n"
        f"🖼 에셋: {len(hashes)}개\n"
        f"💰 트래픽 ₩{BUDGET_TRAFFIC:,} / 잠재 ₩{BUDGET_LATENT:,}\n\n"
        f"대시보드에서 확인 후 ACTIVE 전환해주세요."
    )
    print(f"  ✅ 완료: {name}")


# ── 메인 ─────────────────────────────────────────────────────────────

def main():
    print(f"캠페인 자동 생성 시작 (DB: {CAMPAIGN_DB_ID})")
    pages = query_pending()
    if not pages:
        print("'대기' 상태 행사 없음.")
        return

    print(f"{len(pages)}개 행사 처리 시작...")
    for page in pages:
        try:
            process(page)
        except Exception as e:
            info = parse_campaign(page)
            print(f"  ❌ 실패: {info.get('공연명', '?')} — {e}")
            send_message(f"❌ [{info.get('공연명', '?')}] 캠페인 생성 실패\n오류: {e}")

    print("\n완료.")


if __name__ == "__main__":
    main()

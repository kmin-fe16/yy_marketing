"""D-30 자동 업로드: 노션 DB에서 오늘 광고시작일인 행사를 Meta에 PAUSED로 생성."""
import os
import sys
import requests
from datetime import date
from dotenv import load_dotenv
from notion_client_helper import query_campaigns, update_campaign, parse_campaign
from telegram_bot import send_message

load_dotenv()

TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT = os.getenv("META_AD_ACCOUNT_ID", "act_810493558680773")
API = f"https://graph.facebook.com/{os.getenv('META_API_VERSION', 'v20.0')}"

# 지역명 → Meta 지역 타겟 코드 (주요 지역)
REGION_MAP = {
    "서울": "KR:Seoul",
    "부산": "KR:Busan",
    "대구": "KR:Daegu",
    "인천": "KR:Incheon",
    "광주": "KR:Gwangju",
    "대전": "KR:Daejeon",
    "울산": "KR:Ulsan",
    "세종": "KR:Sejong-si",
    "수원": "KR:Gyeonggi-do",
    "성남": "KR:Gyeonggi-do",
    "부천": "KR:Gyeonggi-do",
    "마포": "KR:Seoul",
    "서초": "KR:Seoul",
    "평택": "KR:Gyeonggi-do",
    "창원": "KR:South Gyeongsang",
}


def create_campaign(campaign_name: str) -> str:
    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/campaigns",
        params={"access_token": TOKEN},
        json={
            "name": campaign_name,
            "objective": "OUTCOME_TRAFFIC",
            "status": "PAUSED",
            "special_ad_categories": [],
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_adset(campaign_id: str, info: dict) -> str:
    # 나이 범위 설정
    age_min, age_max = 40, 54
    if "40대" in info["연령대"] and "50대" not in info["연령대"]:
        age_min, age_max = 40, 49
    elif "50대" in info["연령대"] and "40대" not in info["연령대"]:
        age_min, age_max = 50, 59

    # 성별 (1=남, 2=여)
    genders = [2] if info["성별"] == "여성" else [1] if info["성별"] == "남성" else []

    # 지역 타겟
    region_key = next((k for k in REGION_MAP if k in info["지역"]), None)
    geo_locations = {
        "cities": [{"key": REGION_MAP[region_key]}] if region_key else [],
        "country_groups": [] if region_key else [{"key": "KR"}],
    }

    targeting = {
        "age_min": age_min,
        "age_max": age_max,
        "genders": genders,
        "geo_locations": geo_locations,
        "facebook_positions": ["feed", "instagram_stream"],
        "publisher_platforms": ["facebook", "instagram"],
    }

    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adsets",
        params={"access_token": TOKEN},
        json={
            "name": f"{info['공연명']} — 광고세트",
            "campaign_id": campaign_id,
            "daily_budget": int(info["일예산"]),
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LINK_CLICKS",
            "targeting": targeting,
            "multi_advertiser_eligibility": "INELIGIBLE",
            "status": "PAUSED",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_ad(adset_id: str, info: dict, asset_url: str, label: str) -> str:
    # 크리에이티브 생성
    creative_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adcreatives",
        params={"access_token": TOKEN},
        json={
            "name": f"{info['공연명']} {label}",
            "object_story_spec": {
                "page_id": _get_page_id(),
                "link_data": {
                    "image_url": asset_url,
                    "link": info["랜딩URL"],
                    "message": info["광고본문"],
                    "name": info["광고제목"],
                    "call_to_action": {"type": "LEARN_MORE", "value": {"link": info["랜딩URL"]}},
                },
            },
            "multi_advertiser_eligibility": "INELIGIBLE",
        },
        timeout=15,
    )
    creative_resp.raise_for_status()
    creative_id = creative_resp.json()["id"]

    # 광고 생성
    ad_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/ads",
        params={"access_token": TOKEN},
        json={
            "name": f"{info['공연명']} {label}",
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
        timeout=15,
    )
    ad_resp.raise_for_status()
    return ad_resp.json()["id"]


def _get_page_id() -> str:
    """광고 계정의 첫 번째 페이지 ID 반환."""
    resp = requests.get(
        f"{API}/{AD_ACCOUNT}/promote_pages",
        params={"access_token": TOKEN, "fields": "id"},
        timeout=10,
    )
    if resp.ok:
        data = resp.json().get("data", [])
        if data:
            return data[0]["id"]
    return ""


def process_campaign(page: dict):
    info = parse_campaign(page)
    name = info["공연명"]
    print(f"\n  처리 중: {name}")

    try:
        # 1. 캠페인 생성
        camp_id = create_campaign(f"{name} — 자동생성")
        print(f"    캠페인 생성: {camp_id}")

        # 2. 광고세트 생성
        adset_id = create_adset(camp_id, info)
        print(f"    광고세트 생성: {adset_id}")

        # 3. 에셋 A/B/C 광고 생성
        assets = [
            (info["에셋A"], "에셋A"),
            (info["에셋B"], "에셋B"),
            (info["에셋C"], "에셋C"),
        ]
        created_ads = []
        for url, label in assets:
            if url:
                ad_id = create_ad(adset_id, info, url, label)
                created_ads.append(label)
                print(f"    {label} 광고 생성: {ad_id}")

        # 4. 노션 업데이트
        update_campaign(info["page_id"], {
            "상태": "업로드완료",
            "Meta 캠페인ID": camp_id,
            "Meta 광고세트ID": adset_id,
        })

        # 5. 텔레그램 알림
        send_message(
            f"🎭 <b>[{name}] 캠페인 준비 완료</b>\n\n"
            f"📍 지역: {info['지역']}\n"
            f"📅 공연일: {info['공연일']}\n"
            f"💰 일예산: ₩{int(info['일예산']):,}\n"
            f"🖼 에셋: {', '.join(created_ads)}\n\n"
            f"대시보드에서 내용 확인 후 [승인] 버튼을 눌러주세요."
        )
        print(f"  ✅ 완료: {name}")

    except Exception as e:
        print(f"  ❌ 실패: {name} — {e}")
        send_message(f"❌ [{name}] 캠페인 생성 실패\n오류: {e}")


def main():
    today = date.today().isoformat()
    print(f"D-30 자동 업로드 실행 ({today})")

    pages = query_campaigns(filter_status="대기", ad_start_date=today)
    if not pages:
        print("오늘 업로드할 캠페인 없음.")
        return

    print(f"{len(pages)}개 캠페인 처리 시작...")
    for page in pages:
        process_campaign(page)

    print("\n완료.")


if __name__ == "__main__":
    main()

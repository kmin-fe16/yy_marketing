"""D+2 자동 최적화: 에셋 CTR 비교 → 승자 예산 30% 증액 + 패자 OFF."""
import os
import requests
from datetime import date, timedelta
from dotenv import load_dotenv
from notion_client_helper import query_campaigns, update_campaign, parse_campaign
from telegram_bot import send_message

load_dotenv()

TOKEN = os.getenv("META_ACCESS_TOKEN")
API = f"https://graph.facebook.com/{os.getenv('META_API_VERSION', 'v20.0')}"


def get_ads_insights(adset_id: str) -> list:
    """광고세트 내 에셋별 CTR/spend 조회."""
    resp = requests.get(
        f"{API}/{adset_id}/ads",
        params={
            "fields": "id,name,status,insights{ctr,spend,impressions,clicks}",
            "access_token": TOKEN,
        },
        timeout=15,
    )
    resp.raise_for_status()
    ads = resp.json().get("data", [])

    results = []
    for ad in ads:
        ins = ad.get("insights", {}).get("data", [{}])[0]
        results.append({
            "id": ad["id"],
            "name": ad["name"],
            "status": ad["status"],
            "ctr": float(ins.get("ctr", 0)),
            "spend": float(ins.get("spend", 0)),
            "impressions": int(ins.get("impressions", 0)),
        })
    return sorted(results, key=lambda x: x["ctr"], reverse=True)


def get_adset_budget(adset_id: str) -> int:
    resp = requests.get(
        f"{API}/{adset_id}",
        params={"fields": "daily_budget", "access_token": TOKEN},
        timeout=10,
    )
    resp.raise_for_status()
    return int(resp.json().get("daily_budget", 0))


def set_adset_budget(adset_id: str, new_budget: int):
    requests.post(
        f"{API}/{adset_id}",
        params={"access_token": TOKEN},
        json={"daily_budget": new_budget},
        timeout=10,
    ).raise_for_status()


def pause_ad(ad_id: str):
    requests.post(
        f"{API}/{ad_id}",
        params={"access_token": TOKEN},
        json={"status": "PAUSED"},
        timeout=10,
    ).raise_for_status()


def process_optimization(page: dict):
    info = parse_campaign(page)
    name = info["공연명"]
    adset_id = info["광고세트ID"]

    if not adset_id:
        print(f"  광고세트ID 없음: {name}")
        return

    print(f"\n  최적화 중: {name}")

    try:
        ads = get_ads_insights(adset_id)
        active_ads = [a for a in ads if a["impressions"] > 0]

        if len(active_ads) < 2:
            print(f"  데이터 부족 (활성 에셋 {len(active_ads)}개) — 스킵")
            return

        winner = active_ads[0]
        losers = active_ads[1:]

        # 패자 OFF
        paused = []
        for loser in losers:
            pause_ad(loser["id"])
            paused.append(loser["name"])
            print(f"    ❌ OFF: {loser['name']} (CTR {loser['ctr']:.2f}%)")

        # 승자 예산 30% 증액
        current_budget = get_adset_budget(adset_id)
        new_budget = int(current_budget * 1.3)
        set_adset_budget(adset_id, new_budget)
        print(f"    ✅ 승자: {winner['name']} (CTR {winner['ctr']:.2f}%)")
        print(f"    예산: ₩{current_budget:,} → ₩{new_budget:,}")

        # 노션 업데이트
        update_campaign(info["page_id"], {"상태": "최적화완료"})

        # 텔레그램 알림
        paused_str = "\n".join(f"   ❌ {n}" for n in paused) or "  없음"
        send_message(
            f"⚡ <b>[{name}] 자동 최적화 완료</b>\n\n"
            f"🏆 승자: {winner['name']}\n"
            f"   CTR: {winner['ctr']:.2f}%  |  소진: ₩{int(winner['spend']):,}\n\n"
            f"패자 OFF:\n{paused_str}\n\n"
            f"💰 예산: ₩{current_budget:,} → ₩{new_budget:,} (+30%)"
        )

    except Exception as e:
        print(f"  ❌ 실패: {name} — {e}")
        send_message(f"❌ [{name}] 최적화 실패\n오류: {e}")


def main():
    today = date.today()
    d_plus_2 = (today - timedelta(days=2)).isoformat()
    print(f"D+2 자동 최적화 실행 ({today}) — 집행시작일: {d_plus_2}")

    pages = query_campaigns(filter_status="집행중")
    target = [p for p in pages
              if parse_campaign(p).get("집행시작일") == d_plus_2]

    if not target:
        print("오늘 최적화할 캠페인 없음.")
        return

    print(f"{len(target)}개 캠페인 최적화 시작...")
    for page in target:
        process_optimization(page)

    print("\n완료.")


if __name__ == "__main__":
    main()

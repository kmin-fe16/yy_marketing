"""D+2 자동 최적화: 에셋 CTR 비교 → 승자 예산 30% 증액 + 패자 OFF.
   h48_asset이 사전 선택된 경우 CTR 조회 없이 해당 에셋을 승자로 사용.
"""
import os
import json
import requests
from datetime import date, timedelta
from dotenv import load_dotenv
from notion_client_helper import query_campaigns, update_campaign, parse_campaign
from telegram_bot import send_message

load_dotenv()

TOKEN = os.getenv("META_ACCESS_TOKEN")
API = f"https://graph.facebook.com/{os.getenv('META_API_VERSION', 'v20.0')}"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_LOG_FILE = os.path.join(BASE_DIR, "logs", "upload_log.json")

# A→1, B→2, C→3 (create_campaign에서 에셋 순서대로 -1/-2/-3 suffix)
_ASSET_NUM = {"A": "1", "B": "2", "C": "3"}


def _load_h48_preset() -> dict:
    """upload_log에서 캠페인ID별 h48_asset 사전 선택값 로드."""
    try:
        with open(UPLOAD_LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
        return {e["캠페인ID"]: e.get("h48_asset", "") for e in log if e.get("캠페인ID") and e.get("h48_asset")}
    except Exception:
        return {}


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


def process_optimization(page: dict, h48_presets: dict = None):
    info = parse_campaign(page)
    name = info["공연명"]
    adset_id = info["광고세트ID"]
    campaign_id = info.get("캠페인ID", "")

    if not adset_id:
        print(f"  광고세트ID 없음: {name}")
        return

    print(f"\n  최적화 중: {name}")

    # h48_asset 사전 선택 여부 확인
    preset_asset = (h48_presets or {}).get(campaign_id, "")
    preset_num = _ASSET_NUM.get(preset_asset, "") if preset_asset else ""

    try:
        ads = get_ads_insights(adset_id)
        all_ads = [a for a in ads]  # 전체 (PAUSED 포함)

        if not all_ads:
            print(f"  광고 없음 — 스킵")
            return

        if preset_num:
            # 사전 선택된 에셋 사용 (이름 suffix -N 매칭)
            winner_list = [a for a in all_ads if a["name"].endswith(f"-{preset_num}")]
            if not winner_list:
                print(f"  ⚠️  사전 선택 에셋{preset_asset}(-{preset_num}) 매칭 실패 — CTR로 대체")
                winner_list = sorted([a for a in all_ads if a["impressions"] > 0],
                                     key=lambda x: x["ctr"], reverse=True)
            else:
                print(f"  📌 사전 선택 에셋 {preset_asset} 사용 (CTR 조회 생략)")
            if not winner_list:
                print(f"  데이터 부족 — 스킵")
                return
            winner = winner_list[0]
            losers = [a for a in all_ads if a["id"] != winner["id"]]
        else:
            active_ads = [a for a in all_ads if a["impressions"] > 0]
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
            ctr_str = f" (CTR {loser['ctr']:.2f}%)" if loser.get("impressions", 0) > 0 else ""
            print(f"    ❌ OFF: {loser['name']}{ctr_str}")

        # 승자 예산 30% 증액
        current_budget = get_adset_budget(adset_id)
        new_budget = int(current_budget * 1.3)
        set_adset_budget(adset_id, new_budget)
        ctr_info = f" (CTR {winner['ctr']:.2f}%)" if winner.get("impressions", 0) > 0 else ""
        print(f"    ✅ 승자: {winner['name']}{ctr_info}")
        print(f"    예산: ₩{current_budget:,} → ₩{new_budget:,}")

        # 노션 업데이트
        update_campaign(info["page_id"], {"상태": "최적화완료"})

        # 텔레그램 알림
        paused_str = "\n".join(f"   ❌ {n}" for n in paused) or "  없음"
        preset_note = f"📌 사전선택 에셋{preset_asset}\n" if preset_asset else ""
        send_message(
            f"⚡ <b>[{name}] 자동 최적화 완료</b>\n\n"
            f"{preset_note}"
            f"🏆 승자: {winner['name']}\n\n"
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

    h48_presets = _load_h48_preset()
    print(f"{len(target)}개 캠페인 최적화 시작... (사전선택 {len(h48_presets)}건)")
    for page in target:
        process_optimization(page, h48_presets)

    print("\n완료.")


if __name__ == "__main__":
    main()

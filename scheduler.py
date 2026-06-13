"""
매일 09:00 launchd 실행 — D-day 기준 Meta 광고 자동 업로드 + dry-run 알람 기록.

D-day 스케줄:
  D-35 → 1차, D-31 → 2차, D-27 → 3차, D-24 → 영상,
  D-21 → 잠재, D-17 → 4차, D-12 → 5차
"""
import os
import json
import sys
import requests
from collections import defaultdict
from datetime import date
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRY_RUN_FILE = os.path.join(BASE_DIR, "logs", "dry_run_alerts.json")

DDAY_SCHEDULE = {
    35: "1차",
    31: "2차",
    27: "3차",
    24: "영상",
    21: "잠재",
    17: "4차",
    12: "5차",
}


def _fetch_all_pages() -> list:
    token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("CAMPAIGN_NOTION_DB_ID")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            headers=headers, json=body, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def _load_alerts() -> list:
    if os.path.exists(DRY_RUN_FILE):
        with open(DRY_RUN_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_alerts(alerts: list):
    os.makedirs(os.path.dirname(DRY_RUN_FILE), exist_ok=True)
    with open(DRY_RUN_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def main():
    from notion_client_helper import parse_campaign
    import create_campaign as cc

    today = date.today()
    print(f"[스케줄러] {today} 실행 시작")

    pages = _fetch_all_pages()
    all_camps = [parse_campaign(p) for p in pages]
    print(f"[스케줄러] 총 {len(all_camps)}개 캠페인 조회")

    # 공연날짜별 그룹화
    by_perf: dict = defaultdict(list)
    for c in all_camps:
        if c.get("공연날짜"):
            by_perf[c["공연날짜"][:10]].append(c)

    alerts = _load_alerts()
    # 중복 방지용 키 (공연날짜 + 공연명 + 차수)
    existing_keys = {(a["공연날짜"], a["공연명"], a["차수"]) for a in alerts}

    for perf_date_str, camps in by_perf.items():
        try:
            perf_date = date.fromisoformat(perf_date_str)
        except ValueError:
            continue

        days_until = (perf_date - today).days
        if days_until not in DDAY_SCHEDULE:
            continue

        required_차수 = DDAY_SCHEDULE[days_until]
        perf_name = camps[0].get("공연명", "?")

        matching = [c for c in camps if c.get("차수") == required_차수]

        if not matching:
            # 해당 차수 세팅 자체가 없음 → dry-run 알람
            key = (perf_date_str, perf_name, required_차수)
            if key not in existing_keys:
                print(f"  ⚠️  DRY-RUN: [{perf_name}] D-{days_until} — {required_차수} 세팅 없음")
                alerts.append({
                    "date": today.isoformat(),
                    "공연날짜": perf_date_str,
                    "공연명": perf_name,
                    "차수": required_차수,
                    "dday": days_until,
                    "msg": f"D-{days_until} 예약일인데 {required_차수} 광고 세팅이 없습니다.",
                })
                existing_keys.add(key)
            continue

        # 이미 업로드완료 or 집행중이면 스킵
        pending = [c for c in matching if c.get("상태") == "대기"]
        if not pending:
            print(f"  ✅ SKIP: [{perf_name}] {required_차수} — 이미 처리됨")
            continue

        # 대기 상태인 것 업로드
        for camp in pending:
            original_page = next((p for p in pages if p["id"] == camp["page_id"]), None)
            if not original_page:
                continue
            print(f"  🚀 업로드: [{perf_name}] {required_차수} (D-{days_until})")
            try:
                cc.process(original_page)
                print(f"  ✅ 완료: [{perf_name}] {required_차수}")
            except Exception as e:
                print(f"  ❌ 실패: [{perf_name}] {required_차수} — {e}")

    _save_alerts(alerts)
    print(f"[스케줄러] 완료")


if __name__ == "__main__":
    sys.exit(main())

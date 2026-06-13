"""노션 업로드완료/집행중 캠페인 → upload_log.json 백필 (1회 실행용)"""
import os, json, requests
from dotenv import load_dotenv
from notion_client_helper import parse_campaign
from create_campaign import build_camp_name

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_LOG_FILE = os.path.join(BASE_DIR, "logs", "upload_log.json")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("CAMPAIGN_NOTION_DB_ID")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def fetch_all_done() -> list:
    pages = []
    for status in ["업로드완료", "집행중"]:
        cursor = None
        while True:
            body = {
                "filter": {"property": "상태", "select": {"equals": status}},
                "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            resp = requests.post(
                f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                headers=HEADERS, json=body, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            pages.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    return pages


def main():
    os.makedirs(os.path.dirname(UPLOAD_LOG_FILE), exist_ok=True)

    try:
        with open(UPLOAD_LOG_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    existing_ids = {e.get("캠페인ID") for e in existing if e.get("캠페인ID")}

    print("노션에서 업로드완료/집행중 캠페인 조회 중...")
    pages = fetch_all_done()
    print(f"  → {len(pages)}건 조회됨")

    new_entries = []
    for page in pages:
        info = parse_campaign(page)
        cid = info.get("캠페인ID", "")
        if cid and cid in existing_ids:
            continue
        last_edited = page.get("last_edited_time", "")[:16].replace("T", " ")
        try:
            camp_name = build_camp_name(info)
        except Exception:
            camp_name = info.get("공연명", "")
        print(f"  추가: {camp_name}")
        new_entries.append({
            "uploaded_at": last_edited,
            "캠페인명": camp_name,
            "차수": info.get("차수", ""),
            "공연명": info.get("공연명", ""),
            "에셋A": info.get("에셋A", ""),
            "에셋B": info.get("에셋B", ""),
            "에셋C": info.get("에셋C", ""),
            "캠페인ID": cid,
            "status": "성공",
            "active": False,
        })

    merged = new_entries + existing
    with open(UPLOAD_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged[:200], f, ensure_ascii=False, indent=2)

    print(f"완료: {len(new_entries)}건 추가 (기존 {len(existing)}건 유지)")


if __name__ == "__main__":
    main()

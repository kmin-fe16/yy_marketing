"""노션 본문 파싱 확인용 스크립트."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("CAMPAIGN_NOTION_DB_ID")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

resp = requests.post(
    f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
    headers=HEADERS,
    json={"filter": {"property": "상태", "select": {"equals": "대기"}}, "page_size": 1},
    timeout=15,
)
resp.raise_for_status()
pages = resp.json().get("results", [])

if not pages:
    print("대기 상태 캠페인 없음")
else:
    props = pages[0]["properties"]
    for key in ["A 본문", "B 본문", "C 본문"]:
        raw = props.get(key, {})
        items = raw.get("rich_text", [])
        print(f"\n=== {key} ===")
        print(f"  items 개수: {len(items)}")
        for i, item in enumerate(items):
            print(f"  [{i}] plain_text: {repr(item['plain_text'])}")
        print(f"  합친 결과: {repr(''.join(i['plain_text'] for i in items))}")

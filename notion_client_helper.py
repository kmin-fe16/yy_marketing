"""노션 API 헬퍼 — 캠페인 DB 읽기/쓰기."""
import os
import requests
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID", "e4ea3f29-f959-47ae-ae02-496c804502fb")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def query_campaigns(filter_status: str = None, ad_start_date: str = None) -> list:
    """DB 조회. filter_status: '대기'|'업로드완료'|'집행중' 등"""
    filters = []
    if filter_status:
        filters.append({"property": "상태", "select": {"equals": filter_status}})
    if ad_start_date:
        filters.append({"property": "광고시작일", "date": {"equals": ad_start_date}})

    body = {}
    if len(filters) == 1:
        body["filter"] = filters[0]
    elif len(filters) > 1:
        body["filter"] = {"and": filters}

    resp = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=HEADERS,
        json=body,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def update_campaign(page_id: str, updates: dict) -> bool:
    """페이지 속성 업데이트. updates 예: {'상태': '집행중', 'Meta 캠페인ID': '123'}"""
    properties = {}
    for key, val in updates.items():
        if key == "상태":
            properties[key] = {"select": {"name": val}}
        elif key in ("Meta 캠페인ID", "Meta 광고세트ID", "지역", "광고제목", "광고본문", "메모"):
            properties[key] = {"rich_text": [{"text": {"content": str(val)}}]}
        elif key in ("집행시작일", "광고시작일", "공연일"):
            properties[key] = {"date": {"start": str(val)}}
        elif key == "일예산":
            properties[key] = {"number": float(val)}

    resp = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": properties},
        timeout=15,
    )
    return resp.ok


def get_seat_by_date() -> dict:
    """공연일 기준 좌석수 반환. {(month, day): seat_count}
    공연일 미입력 시 공연명(26MMDD...)에서 날짜 파싱.
    """
    import re
    from datetime import datetime
    try:
        pages = query_campaigns()
        result = {}
        for page in pages:
            c = parse_campaign(page)
            if not c["좌석수"]:
                continue
            key = None
            if c["공연일"]:
                d = datetime.fromisoformat(c["공연일"])
                key = (d.month, d.day)
            else:
                m = re.match(r"26(\d{2})(\d{2})", c["공연명"].strip())
                if m:
                    key = (int(m.group(1)), int(m.group(2)))
            if key:
                result[key] = int(c["좌석수"])
        print(f"[노션] 좌석수 {len(result)}개 행사 조회 완료")
        return result
    except Exception as e:
        print(f"[노션] 좌석수 조회 실패: {e}")
        return {}


def parse_campaign(page: dict) -> dict:
    """노션 페이지에서 캠페인 정보 추출."""
    props = page["properties"]

    def text(key):
        items = props.get(key, {}).get("rich_text", [])
        return items[0]["plain_text"] if items else ""

    def title(key):
        items = props.get(key, {}).get("title", [])
        return items[0]["plain_text"] if items else ""

    def date_val(key):
        d = props.get(key, {}).get("date")
        return d["start"] if d else None

    def select_val(key):
        s = props.get(key, {}).get("select")
        return s["name"] if s else None

    def multi_select(key):
        return [o["name"] for o in props.get(key, {}).get("multi_select", [])]

    def url_val(key):
        return props.get(key, {}).get("url") or ""

    def checkbox(key):
        return props.get(key, {}).get("checkbox", False)

    def number(key):
        return props.get(key, {}).get("number") or 0

    return {
        "page_id": page["id"],
        "공연명": title("공연명"),
        "지역": text("지역"),
        "공연일": date_val("공연일"),
        "광고시작일": date_val("광고시작일"),
        "일예산": number("일예산"),
        "연령대": multi_select("연령대"),
        "성별": select_val("성별") or "여성",
        "지역확장": checkbox("지역확장"),
        "광고제목": text("광고제목"),
        "광고본문": text("광고본문"),
        "에셋A": url_val("에셋A URL"),
        "에셋B": url_val("에셋B URL"),
        "에셋C": url_val("에셋C URL"),
        "랜딩URL": url_val("랜딩URL"),
        "상태": select_val("상태"),
        "캠페인ID": text("Meta 캠페인ID"),
        "광고세트ID": text("Meta 광고세트ID"),
        "집행시작일": date_val("집행시작일"),
        "좌석수": number("좌석수"),
        "차수": text("차수") or "1차",
    }

"""노션 API 헬퍼 — 캠페인 DB 읽기/쓰기."""
import os
import requests
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("CAMPAIGN_NOTION_DB_ID")
# 2026 공연일정 DB — 좌석수 롤업이 대관장소 DB와 연결되어 있음
PERFORMANCE_DB_ID = os.getenv("PERFORMANCE_DB_ID", "32839fb1f9d680ef9f60c7b0b0d04672")
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
        elif key in ("Meta 캠페인 ID", "Meta 광고세팅 ID", "지역", "A 제목", "B 제목", "C 제목", "A 본문", "B 본문", "C 본문", "메모"):
            properties[key] = {"rich_text": [{"text": {"content": str(val)}}]}
        elif key in ("광고시작일", "공연일"):
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


def get_seat_by_date() -> tuple:
    """2026 공연일정 DB에서 날짜 기준 좌석수, 장소명 반환.
    Returns: ({(month, day): seat_count}, {(month, day): venue_name})
    """
    try:
        all_pages = []
        cursor = None
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = requests.post(
                f"https://api.notion.com/v1/databases/{PERFORMANCE_DB_ID}/query",
                headers=HEADERS,
                json=body,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            all_pages.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        seats = {}
        venues = {}
        for page in all_pages:
            props = page["properties"]
            date_prop = props.get("공연날짜", {})
            if date_prop.get("type") == "rollup":
                arr = date_prop.get("rollup", {}).get("array", [])
                date_start = next((i["date"]["start"] for i in arr if i.get("type") == "date" and i.get("date")), None)
            else:
                dv = date_prop.get("date")
                date_start = dv["start"] if dv else None
            if not date_start:
                continue
            d = datetime.fromisoformat(date_start)
            key = (d.month, d.day)

            seat_arr = props.get("좌석수", {}).get("rollup", {}).get("array", [])
            seat = seat_arr[0].get("number") if seat_arr else None
            if seat and key not in seats:
                seats[key] = int(seat)

            venue_arr = props.get("주소", {}).get("rollup", {}).get("array", [])
            if venue_arr and key not in venues:
                item = venue_arr[0]
                if item.get("type") == "title":
                    title_items = item.get("title", [])
                    venues[key] = title_items[0].get("plain_text", "") if title_items else ""
                elif item.get("type") == "rich_text":
                    rt_items = item.get("rich_text", [])
                    venues[key] = rt_items[0].get("plain_text", "") if rt_items else ""

        print(f"[노션] 좌석수 {len(seats)}개, 장소명 {len(venues)}개 행사 조회 완료")
        return seats, venues
    except Exception as e:
        print(f"[노션] 좌석수 조회 실패: {e}")
        return {}, {}


def _fetch_page(page_id: str) -> dict:
    resp = requests.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def parse_campaign(page: dict) -> dict:
    """노션 페이지에서 캠페인 정보 추출."""
    props = page["properties"]

    def text(key):
        items = props.get(key, {}).get("rich_text", [])
        return "".join(i["plain_text"] for i in items)

    def title(key):
        items = props.get(key, {}).get("title", [])
        return "".join(i["plain_text"] for i in items)

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

    def number(key):
        return props.get(key, {}).get("number") or 0

    def rollup_date(key):
        arr = props.get(key, {}).get("rollup", {}).get("array", [])
        for item in arr:
            if item.get("type") == "date" and item.get("date"):
                return item["date"]["start"]
        return None

    def rollup_select(key):
        arr = props.get(key, {}).get("rollup", {}).get("array", [])
        for item in arr:
            if item.get("type") == "select" and item.get("select"):
                return item["select"]["name"]
        return None

    # 공연장소: 🗓️ 2026 공연일정 관련 페이지 → 주소 rollup title
    공연장소 = ""
    try:
        schedule_ids = props.get("🗓️ 2026 공연일정", {}).get("relation", [])
        if schedule_ids:
            sched = _fetch_page(schedule_ids[0]["id"])
            addr_arr = sched["properties"].get("주소", {}).get("rollup", {}).get("array", [])
            for item in addr_arr:
                if item.get("type") == "title":
                    t_items = item.get("title", [])
                    공연장소 = t_items[0]["plain_text"] if t_items else ""
                    break
    except Exception:
        pass

    return {
        "page_id": page["id"],
        "공연명": title("공연명"),
        "공연날짜": rollup_date("공연날짜"),
        "공연장소": 공연장소,
        "행사구분": rollup_select("행사구분") or "",
        "차수": select_val("차수") or "1차",
        "광고시작일": date_val("광고시작일"),
        "일예산": number("일예산"),
        "광고제목A": text("A 제목"),
        "광고제목B": text("B 제목"),
        "광고제목C": text("C 제목"),
        "광고본문A": text("A 본문"),
        "광고본문B": text("B 본문"),
        "광고본문C": text("C 본문"),
        "에셋A": url_val("에셋A_url"),
        "에셋B": url_val("에셋B_url"),
        "에셋C": url_val("에셋C_url"),
        "랜딩URL": url_val("랜딩URL"),
        "잠재폼id": text("잠재폼id"),
        "상태": select_val("상태"),
        "캠페인ID": text("Meta 캠페인 ID"),
        "광고세트ID": text("Meta 광고세팅 ID"),
    }


def find_latest_settings(공연명: str, 공연날짜: str = None):
    """동일 공연날짜에서 가장 최근 업로드완료된 비-잠재 row의 세팅값 반환."""
    if not 공연날짜:
        return None

    filters = [
        {"property": "공연날짜", "rollup": {"any": {"date": {"equals": 공연날짜}}}},
        {"property": "상태", "select": {"equals": "업로드완료"}},
        {"property": "차수", "select": {"does_not_equal": "잠재"}},
    ]
    resp = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=HEADERS,
        json={
            "filter": {"and": filters},
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            "page_size": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    return parse_campaign(results[0])

import os
import re
import sys
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

ADMIN_URL = "https://yeoyoutalk.kr/abcadmin"
ADMIN_ID = os.getenv("YEYOUTALK_ID")
ADMIN_PW = os.getenv("YEYOUTALK_PW")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
def login():
    if not ADMIN_ID or not ADMIN_PW:
        raise RuntimeError(".env 파일에 YEYOUTALK_ID와 YEYOUTALK_PW를 입력하세요.")
    session = requests.Session()
    resp = session.post(
        f"{ADMIN_URL}/login_ok.asp",
        data={"str_id": ADMIN_ID, "str_pw": ADMIN_PW},
        headers=HEADERS, timeout=10,
    )
    if "등록되지 않은" in resp.text:
        raise RuntimeError("여유톡 로그인 실패 — 아이디/비밀번호 확인")
    return session


def get_active_events(session):
    """event_input 목록에서 반영=Y인 행사명 추출."""
    events = []
    page = 1
    while True:
        resp = session.get(
            f"{ADMIN_URL}/event_input/index.asp?search_view=Y&page={page}",
            headers=HEADERS, timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")

        found = False
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [td.get_text(strip=True) for td in rows[0].find_all(["th", "td"])]
            # 깔끔한 헤더 테이블: 첫 셀이 "번호"이고 "행사명" 포함
            if headers[0] != "번호" or "행사명" not in headers:
                continue
            idx_name = headers.index("행사명")
            idx_view = headers.index("반영") if "반영" in headers else None
            for tr in rows[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) <= idx_name:
                    continue
                if cells[idx_name]:
                    events.append(cells[idx_name])
            found = True
            break

        if not found:
            break

        next_link = soup.find("a", string=re.compile(r"다음|next", re.I))
        if not next_link:
            break
        page += 1

    def sort_key(name):
        m = re.match(r"(\d+)/(\d+)", name)
        return (int(m.group(1)), int(m.group(2))) if m else (99, 99)

    return sorted(set(events), key=sort_key)


def count_applicants(session, event_name):
    """행사명으로 검색 후 첫 번째 행의 번호값(= 전체 건수) 반환. 요청 1번."""
    resp = session.post(
        f"{ADMIN_URL}/exhibition/index.asp",
        data={"search_title": event_name, "search_listview": "5", "page": "1"},
        headers={**HEADERS, "Referer": f"{ADMIN_URL}/exhibition/index.asp"},
        timeout=30,
    )
    soup = BeautifulSoup(resp.text, "html.parser")

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        if len(header_cells) < 5:
            continue
        headers = [td.get_text(strip=True) for td in header_cells]
        if headers[1] != "번호" or headers[2] != "회원상태":
            continue
        for tr in rows[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and cells[1].isdigit():
                return int(cells[1])  # 첫 번째 행 번호 = 전체 건수
    return 0


def main():
    try:
        session = login()
    except RuntimeError as e:
        print(f"[오류] {e}")
        sys.exit(1)
    print("[성공] 로그인 완료\n")

    print("반영 중인 행사 목록 조회...")
    events = get_active_events(session)
    print(f"{len(events)}개 행사 발견\n")

    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_event = {
            executor.submit(count_applicants, session, event): event
            for event in events
        }
        for future in as_completed(future_to_event):
            event = future_to_event[future]
            results[event] = future.result()

    def sort_key(name):
        m = re.match(r"(\d+)/(\d+)", name)
        return (int(m.group(1)), int(m.group(2))) if m else (99, 99)

    print(f"{'행사명':<30} {'신청자수':>8}")
    print("-" * 40)

    total = 0
    for event in sorted(results, key=sort_key):
        count = results[event]
        print(f"{event:<30} {count:>8,}명")
        total += count

    print("-" * 40)
    print(f"{'합계':<30} {total:>8,}명")


if __name__ == "__main__":
    main()

"""당근 광고 — API 또는 CSV 파일에서 캠페인 데이터 조회."""
import os
import re
import csv
import glob
import requests
from datetime import date as date_cls
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DANGGEUN_AD_TOKEN", "")
ACCOUNT_ID = os.getenv("DANGGEUN_AD_ACCOUNT_ID", "")
BASE_URL = "https://advertising.api.daangn.com/v1"


def get_campaigns(today: date_cls = None) -> list:
    """당근 광고 캠페인 조회. 자격증명 없으면 빈 리스트."""
    if not TOKEN or not ACCOUNT_ID:
        return []
    if today is None:
        today = date_cls.today()

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "X-Account-Id": ACCOUNT_ID,
    }

    try:
        resp = requests.get(f"{BASE_URL}/campaigns", headers=headers, timeout=15)
        resp.raise_for_status()
        campaigns = resp.json().get("campaigns", [])
    except Exception as e:
        print(f"[당근] 캠페인 조회 실패: {e}")
        return []

    result = []
    for c in campaigns:
        event_date = _parse_date(c.get("name", ""))
        if not event_date or event_date < today:
            continue

        spend, impressions, clicks, ctr = 0, 0, 0, 0.0
        try:
            stat_resp = requests.get(
                f"{BASE_URL}/campaigns/{c['id']}/stats",
                headers=headers,
                params={"from": "2026-01-01", "to": date_cls.today().isoformat()},
                timeout=10,
            )
            if stat_resp.ok:
                s = stat_resp.json()
                spend = float(s.get("totalCost", 0))
                impressions = int(s.get("totalImpressions", 0))
                clicks = int(s.get("totalClicks", 0))
                ctr = round(clicks / impressions * 100, 2) if impressions else 0.0
        except Exception:
            pass

        result.append({
            "id": str(c.get("id", "")),
            "name": c.get("name", ""),
            "status": "ACTIVE" if c.get("status") == "ACTIVE" else "PAUSED",
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "reach": 0,
            "platform": "danggeun",
            "created": c.get("createdAt", "")[:10],
            "event_date": event_date.isoformat(),
        })
    return result


def get_from_csv(folder: str) -> dict:
    """
    당근마켓 CSV 파일에서 날짜별 성과 읽기.
    반환: {(month, day): {"spend": float, "impressions": int, "clicks": int, "reach": int, "ctr": float}}
    컬럼: 기간, 캠페인 이름, 광고그룹 이름, 비용(VAT포함), 노출 수, 도달 수, 클릭 수, 클릭률, CPC, CPM
    """
    # "당근" 포함 CSV 우선, 없으면 가장 최근 수정 CSV
    candidates = glob.glob(os.path.join(folder, "*당근*.csv"))
    if not candidates:
        candidates = glob.glob(os.path.join(folder, "*.csv"))
    if not candidates:
        return {}

    csv_file = max(candidates, key=os.path.getmtime)
    result = {}

    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            with open(csv_file, encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ad_group = row.get("광고그룹 이름", "").strip()
                    m = re.match(r"26(\d{2})(\d{2})", ad_group)
                    if not m:
                        continue
                    key = (int(m.group(1)), int(m.group(2)))

                    spend = _parse_num(row.get("비용 (VAT 포함)", "0"))
                    impressions = int(_parse_num(row.get("노출 수", "0")))
                    clicks = int(_parse_num(row.get("클릭 수", "0")))
                    reach = int(_parse_num(row.get("도달 수", "0")))

                    if key not in result:
                        result[key] = {"spend": 0.0, "impressions": 0, "clicks": 0, "reach": 0}
                    result[key]["spend"] += spend
                    result[key]["impressions"] += impressions
                    result[key]["clicks"] += clicks
                    result[key]["reach"] += reach
            break  # 성공하면 다른 인코딩 시도 안 함
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"[당근 CSV] 읽기 실패 ({csv_file}): {e}")
            return {}

    for key in result:
        d = result[key]
        d["ctr"] = round(d["clicks"] / d["impressions"] * 100, 2) if d["impressions"] else 0.0

    print(f"[당근 CSV] {os.path.basename(csv_file)} → {len(result)}개 행사 데이터")
    return result


def _parse_num(s: str) -> float:
    try:
        return float(str(s).replace(",", "").replace("₩", "").replace("%", "").strip() or 0)
    except Exception:
        return 0.0


def _parse_date(name: str):
    m = re.match(r"26(\d{2})(\d{2})", name.strip())
    if m:
        try:
            return date_cls(2026, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None

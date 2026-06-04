import requests
import json
import re
import os
from datetime import date as date_cls
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from scrape_applicants import login as yy_login, get_active_events, count_applicants

load_dotenv()

ACCESS_TOKEN = "EAAcS3syXjtcBRqFui6iZBybqqcUYJmjQQCZCSy9zFUY3KN0JRtivnEdRmnmbchMKr4O3j03FIRvVqmZCRtklJ5ijGODGlIZBteZCoGTyf74Pkh8GJ0SXlGIW65r2QW0Ifs6njWqvIjqwU1DfJ6lasdxkLnbeaIuOvo5cVrDZAkufu47dOs8ZC5TZBk1svQnZCqMg2cdOzgYX2C19d4ZBtZAef8j"
AD_ACCOUNT_ID = "act_810493558680773"
API_VERSION = "v20.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


def get_all_active_campaigns():
    campaigns = []
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/campaigns"
    params = {
        "fields": (
            "id,name,status,objective,created_time,"
            "insights.time_range({'since':'2026-01-01','until':'2026-12-31'}){impressions,clicks,spend,reach,ctr,cpc}"
        ),
        "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE","PAUSED"]}]',
        "access_token": ACCESS_TOKEN,
        "limit": 200,
    }
    while url:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        campaigns.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
    return campaigns



def get_all_active_ads():
    """오늘 이후 행사 광고(에셋) 조회 — 썸네일 + insights 포함."""
    ads = []
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/ads"
    params = {
        "fields": (
            "id,name,status,campaign_id,"
            "creative{thumbnail_url},"
            "insights.time_range({'since':'2026-01-01','until':'2026-12-31'}){ctr,cpm,spend,impressions,clicks}"
        ),
        "filtering": '[{"field":"campaign.effective_status","operator":"IN","value":["ACTIVE","PAUSED"]}]',
        "access_token": ACCESS_TOKEN,
        "limit": 500,
    }
    while url:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        ads.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
    return ads


def campaign_date_key(name):
    """Meta 캠페인명 '260609 성남...' → (6, 9)"""
    m = re.match(r"26(\d{2})(\d{2})", name.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def get_applicant_counts():
    """여유톡에서 행사별 신청자 수 반환. 키: (month, day) → count"""
    try:
        session = yy_login()
        events = get_active_events(session)
        results = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(count_applicants, session, e): e for e in events}
            for f in as_completed(futs):
                e = futs[f]
                m = re.match(r"(\d+)/(\d+)", e)
                if m:
                    results[(int(m.group(1)), int(m.group(2)))] = f.result()
        print(f"  → {len(results)}개 행사 신청자 수 수집 완료")
        return results
    except Exception as e:
        print(f"[경고] 여유톡 신청자 수 조회 실패: {e}")
        return {}


def extract_round(name):
    """캠페인명에서 차수 추출. '260609 성남... 5차' → '5차', '...잠재' → '잠재'"""
    parts = name.strip().split()
    for part in reversed(parts):
        if re.search(r'\d+차', part):
            return part
        if part in ('잠재', '잠재고객'):
            return '잠재'
    return parts[-1] if parts else ""


def extract_region(name):
    parts = name.strip().split()
    if len(parts) >= 2:
        return parts[1]
    return "기타"


def fmt_number(val):
    try:
        return f"{int(float(val)):,}"
    except:
        return "-"


def fmt_currency(val):
    try:
        return f"₩{int(float(val)):,}"
    except:
        return "-"


def fmt_pct(val):
    try:
        return f"{float(val):.2f}%"
    except:
        return "-"


def build_approval_html(pending_campaigns=None):
    """승인 대기 전용 페이지 생성. 노션 연결 전: 목업 데이터 사용."""
    MOCK_PENDING = [
        {
            "공연명": "7/5 부산 벡스코",
            "공연일": "2026-07-05",
            "지역": "부산",
            "일예산": 50000,
            "연령대": ["40대", "50대"],
            "광고제목": "여유톡 7월 부산 공연",
            "에셋A": "", "에셋B": "", "에셋C": "",
            "캠페인ID": "MOCK_ID_001",
        },
        {
            "공연명": "7/12 대전 ICC",
            "공연일": "2026-07-12",
            "지역": "대전",
            "일예산": 40000,
            "연령대": ["40대", "50대"],
            "광고제목": "여유톡 7월 대전 공연",
            "에셋A": "", "에셋B": "", "에셋C": "",
            "캠페인ID": "MOCK_ID_002",
        },
    ]
    pending = pending_campaigns if pending_campaigns is not None else MOCK_PENDING

    def card(p):
        is_mock = str(p["캠페인ID"]).startswith("MOCK")
        btn_text = "🔒 목업 (노션 연결 후 활성화)" if is_mock else "🚀 승인 (ACTIVE 전환)"
        disabled = "disabled" if is_mock else ""
        assets_html = "".join(
            f'<img class="asset-thumb" src="{url}" onerror="this.style.background=\'#E4E6EB\';this.src=\'\';">'
            if url else '<div class="asset-thumb asset-empty">🖼</div>'
            for url in [p.get("에셋A",""), p.get("에셋B",""), p.get("에셋C","")]
        )
        return f"""
        <div class="card">
            <div class="card-name">{p['공연명']}</div>
            <div class="card-tags">
                <span>📅 {p['공연일']}</span>
                <span>📍 {p['지역']}</span>
                <span>💰 ₩{int(p['일예산']):,}/일</span>
                <span>👥 {'·'.join(p.get('연령대',['40대','50대']))} 여성</span>
            </div>
            <div class="card-title">📝 {p['광고제목']}</div>
            <div class="card-assets">{assets_html}</div>
            <button class="approve-btn" {disabled}
                onclick="approveCampaign('{p['캠페인ID']}', this)">
                {btn_text}
            </button>
        </div>"""

    cards_html = "".join(card(p) for p in pending)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>승인 대기 | Meta 광고</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F0F2F5; color: #1C1E21; }}
  header {{ background: #1877F2; color: white; padding: 18px 32px; display: flex; align-items: center; justify-content: space-between; }}
  header h1 {{ font-size: 20px; font-weight: 700; }}
  .back-link {{ color: white; text-decoration: none; background: rgba(255,255,255,0.2); padding: 6px 14px; border-radius: 20px; font-size: 13px; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 28px 20px; }}
  .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 18px; color: #E65100; }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 16px; }}
  .card {{ background: white; border-radius: 12px; padding: 18px 20px; min-width: 240px; max-width: 280px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); display: flex; flex-direction: column; gap: 10px; }}
  .card-name {{ font-weight: 700; font-size: 16px; }}
  .card-tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .card-tags span {{ font-size: 11px; background: #F0F2F5; padding: 3px 8px; border-radius: 8px; }}
  .card-title {{ font-size: 12px; color: #606770; }}
  .card-assets {{ display: flex; gap: 8px; }}
  .asset-thumb {{ width: 60px; height: 60px; object-fit: cover; border-radius: 8px; border: 1.5px solid #E4E6EB; }}
  .asset-empty {{ width: 60px; height: 60px; background: #E4E6EB; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 20px; }}
  .approve-btn {{ background: #1877F2; color: white; border: none; padding: 10px 0; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 700; width: 100%; }}
  .approve-btn:hover:not(:disabled) {{ background: #1565C0; }}
  .approve-btn:disabled {{ background: #E4E6EB; color: #999; cursor: not-allowed; }}
  .mock-notice {{ background: #FFF8E1; border: 1px solid #FFD54F; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; color: #E65100; }}
</style>
</head>
<body>
<header>
  <h1>⏳ 승인 대기</h1>
  <a href="dashboard.html" class="back-link">← 대시보드로</a>
</header>
<div class="container">
  <div class="mock-notice">
    📌 현재 목업 데이터입니다. 노션 연결 후 실제 업로드 완료 캠페인이 표시됩니다.
  </div>
  <div class="section-title">승인 대기 {len(pending)}개</div>
  <div class="cards">{cards_html}</div>
</div>
<script>
const ACCESS_TOKEN = "{ACCESS_TOKEN}";
async function approveCampaign(id, btn) {{
  if (!confirm('이 캠페인을 ACTIVE로 전환하시겠습니까?')) return;
  btn.disabled = true; btn.textContent = '처리 중...';
  try {{
    const body = new URLSearchParams({{ status: 'ACTIVE', access_token: ACCESS_TOKEN }});
    const r = await fetch(`https://graph.facebook.com/{API_VERSION}/${{id}}`, {{ method: 'POST', body }});
    const res = await r.json();
    if (res.success) {{
      btn.textContent = '✅ 집행 시작됨';
      btn.style.background = '#E6F4EA'; btn.style.color = '#137333';
    }} else {{
      btn.textContent = '❌ 실패'; btn.disabled = false;
      alert('오류: ' + (res.error?.message || JSON.stringify(res)));
    }}
  }} catch(e) {{ btn.textContent = '❌ 실패'; btn.disabled = false; alert(e.message); }}
}}
</script>
</body>
</html>"""


def build_html(regions_data, totals, ads_by_campaign, platform_by_region=None, pending_campaigns=None):
    colors = ["#4F86C6", "#E07B54", "#5BAD6F", "#9B5EA2", "#D4A843",
              "#E05C87", "#43A8A8", "#8B7355", "#6B7A8D", "#C96B6B"]

    # ── 승인 대기 섹션 (노션 연결 전: 목업 데이터 / 연결 후: 실제 데이터) ──
    MOCK_PENDING = [
        {
            "공연명": "7/5 부산 벡스코",
            "공연일": "2026-07-05",
            "지역": "부산",
            "일예산": 50000,
            "연령대": ["40대", "50대"],
            "광고제목": "여유톡 7월 부산 공연",
            "에셋A": "",
            "에셋B": "",
            "에셋C": "",
            "캠페인ID": "MOCK_ID_001",
        },
        {
            "공연명": "7/12 대전 ICC",
            "공연일": "2026-07-12",
            "지역": "대전",
            "일예산": 40000,
            "연령대": ["40대", "50대"],
            "광고제목": "여유톡 7월 대전 공연",
            "에셋A": "",
            "에셋B": "",
            "에셋C": "",
            "캠페인ID": "MOCK_ID_002",
        },
    ]
    pending = pending_campaigns if pending_campaigns is not None else MOCK_PENDING

    def approval_card(p):
        assets = [(p.get("에셋A",""), "A"), (p.get("에셋B",""), "B"), (p.get("에셋C",""), "C")]
        asset_count = sum(1 for url, _ in assets if url)
        thumbs = "".join(
            f'<img class="pending-thumb" src="{url}" onerror="this.style.background=\'#E4E6EB\';this.src=\'\';">'
            if url else '<div class="pending-thumb pending-thumb-empty"></div>'
            for url, label in assets
        )
        age_str = "/".join(p.get("연령대", ["40대", "50대"]))
        is_mock = p["캠페인ID"].startswith("MOCK")
        btn_text = "🔒 목업 (연결 후 활성화)" if is_mock else "🚀 승인 (ACTIVE 전환)"
        btn_disabled = "disabled" if is_mock else ""
        return f"""
        <div class="pending-card">
            <div class="pending-name">{p['공연명']}</div>
            <div class="pending-meta">
                <span>📅 {p['공연일']}</span>
                <span>📍 {p['지역']}</span>
                <span>💰 ₩{int(p['일예산']):,}/일</span>
                <span>👥 {age_str} 여성</span>
            </div>
            <div class="pending-title">📝 {p['광고제목']}</div>
            <div class="pending-assets">{thumbs}</div>
            <button class="approve-btn" {btn_disabled}
                onclick="approveCampaign('{p['캠페인ID']}', this)">
                {btn_text}
            </button>
        </div>"""

    approval_html = f"""
    <div class="approval-section">
        <div class="approval-title">⏳ 승인 대기 {len(pending)}개
            <span class="approval-sub">노션 연결 후 실제 데이터로 전환됩니다</span>
        </div>
        <div class="approval-list">{"".join(approval_card(p) for p in pending)}</div>
    </div>""" if pending else ""

    region_list = list(regions_data.keys())
    chart_labels = json.dumps([r for r in region_list])
    chart_spend = json.dumps([regions_data[r]["total_spend"] for r in region_list])
    chart_ctr_avg = json.dumps([round(regions_data[r]["avg_ctr"], 2) for r in region_list])
    chart_colors = json.dumps([colors[i % len(colors)] for i in range(len(region_list))])

    # ADS_DATA: campaign_id → ads list (JSON, escaped for embedding)
    ads_data_json = json.dumps(ads_by_campaign).replace('</', '<\\/')

    # 엑셀용 데이터 — 행사별 전체 집계
    excel_rows = []
    for region, data in regions_data.items():
        applicants = data["campaigns"][0].get("applicants", 0) if data["campaigns"] else 0
        # Meta 합계
        meta_spend = data["total_spend"]
        meta_imp = data["total_impressions"]
        meta_clicks = data["total_clicks"]
        # 타 플랫폼
        pbr = (platform_by_region or {}).get(region, {})
        for plat in ["meta", "kakao", "naver", "google", "danggeun"]:
            if plat == "meta":
                s, i, c = meta_spend, meta_imp, meta_clicks
            else:
                d = pbr.get(plat)
                if not d:
                    continue
                s, i, c = d["spend"], d["impressions"], d["clicks"]
            ctr_val = round(c / i * 100, 2) if i else 0
            event_date = ""
            for camp in data["campaigns"]:
                m = re.match(r"26(\d{2})(\d{2})", camp["name"])
                if m:
                    event_date = f"2026-{m.group(1)}-{m.group(2)}"
                    break
            excel_rows.append({
                "행사명": region,
                "공연일": event_date,
                "플랫폼": {"meta":"Meta","kakao":"카카오","naver":"네이버","google":"구글","danggeun":"당근"}.get(plat, plat),
                "소진금액": int(s),
                "노출수": i,
                "클릭수": c,
                "CTR": ctr_val,
                "신청자수": applicants if plat == "meta" else "",
            })
    excel_json = json.dumps(excel_rows, ensure_ascii=False).replace('</', '<\\/')

    PLATFORM_LABELS = {
        "meta": "Meta", "kakao": "카카오", "naver": "네이버",
        "google": "구글", "danggeun": "당근"
    }
    PLATFORM_COLORS = {
        "meta": "#1877F2", "kakao": "#FEE500", "naver": "#03C75A",
        "google": "#4285F4", "danggeun": "#FF6F0F"
    }

    def progress_bar(data):
        seat = data.get("seat_count", 0)
        applicants = data["campaigns"][0].get("applicants", 0) if data["campaigns"] else 0
        if not seat:
            return ""
        target = max(1, round(seat / 0.16))
        pct = min(100, round(applicants / target * 100))
        remaining = max(0, target - applicants)
        fill_color = "#137333" if pct >= 100 else "#1877F2"
        return f"""<div class="progress-wrap">
          <div class="progress-top">
            <span class="progress-label">모객 {pct}%</span>
            <span class="progress-pct">{applicants:,}명 / 목표 {target:,}명</span>
          </div>
          <div class="progress-bg">
            <div class="progress-fill" style="width:{pct}%;background:{fill_color}"></div>
          </div>
          <div class="progress-detail">
            좌석 {seat:,}석 기준 &nbsp;·&nbsp; 잔여 목표 <b>{remaining:,}명</b> &nbsp;·&nbsp; 전환율 16% 적용
          </div>
        </div>"""

    def platform_table(region, meta_data):
        pbr = (platform_by_region or {}).get(region, {})
        rows = []

        # Meta 행 (항상 표시)
        meta_spend = meta_data["total_spend"]
        meta_imp = meta_data["total_impressions"]
        meta_clicks = meta_data["total_clicks"]
        meta_ctr = meta_data["avg_ctr"]
        rows.append(f"""<tr>
            <td><span class="plat-badge" style="background:#E7F0FD;color:#1877F2">Meta</span></td>
            <td>{fmt_currency(meta_spend)}</td>
            <td>{fmt_number(meta_imp)}</td>
            <td>{fmt_number(meta_clicks)}</td>
            <td>{fmt_pct(meta_ctr)}</td>
        </tr>""")

        # 타 플랫폼 행
        for plat in ["kakao", "naver", "google", "danggeun"]:
            if plat not in pbr:
                continue
            d = pbr[plat]
            imp = d["impressions"]
            ctr = round(d["clicks"] / imp * 100, 2) if imp else 0
            color = PLATFORM_COLORS.get(plat, "#888")
            label = PLATFORM_LABELS.get(plat, plat)
            rows.append(f"""<tr>
                <td><span class="plat-badge" style="background:{color}20;color:{color}">{label}</span></td>
                <td>{fmt_currency(d['spend'])}</td>
                <td>{fmt_number(imp)}</td>
                <td>{fmt_number(d['clicks'])}</td>
                <td>{fmt_pct(ctr)}</td>
            </tr>""")

        if len(rows) <= 1 and meta_spend == 0:
            return ""
        return f"""<div class="platform-table-wrap">
            <table class="platform-table">
                <thead><tr><th>플랫폼</th><th>소진금액</th><th>노출수</th><th>클릭수</th><th>CTR</th></tr></thead>
                <tbody>{"".join(rows)}</tbody>
            </table>
        </div>"""

    def creative_strip(campaigns):
        items = []
        for c in sorted(campaigns, key=lambda x: x["spend"], reverse=True):
            thumb = None
            for ad in ads_by_campaign.get(c["id"], []):
                if ad.get("creative", {}).get("thumbnail_url"):
                    thumb = ad["creative"]["thumbnail_url"]
                    break
            round_label = extract_round(c["name"])
            img_html = (f'<img class="creative-thumb" src="{thumb}" '
                        f'onerror="this.style.display=\'none\'">'
                        if thumb else '<div class="creative-thumb-empty"></div>')
            items.append(
                f'<div class="creative-item">'
                f'{img_html}'
                f'<span class="round-label">{round_label}</span>'
                f'</div>'
            )
        return f'<div class="creative-strip">{"".join(items)}</div>'

    def campaign_rows(campaigns):
        rows = []
        for c in sorted(campaigns, key=lambda x: x["spend"], reverse=True):
            cid = c["id"]
            rows.append(f"""
            <tr class="camp-row {'camp-active' if c['status'] == 'ACTIVE' else 'camp-paused'}" onclick="toggleAds(this)" data-campaign-id="{cid}">
                <td class="camp-name">
                    <span class="expand-icon">▶</span> {c['name']}
                </td>
                <td style="font-size:12px;color:#606770;white-space:nowrap">{c.get('created','')[5:].replace('-','/')}</td>
                <td>{fmt_number(c['impressions'])}</td>
                <td>{fmt_number(c['clicks'])}</td>
                <td>
                    <span class="ctr-badge {'ctr-high' if c['ctr'] >= 3 else 'ctr-mid' if c['ctr'] >= 1.5 else 'ctr-low'}">
                        {fmt_pct(c['ctr'])}
                    </span>
                </td>
                <td>{fmt_currency(c['spend'])}</td>
                <td>{fmt_number(c['reach'])}</td>
            </tr>""")
        return "\n".join(rows)

    CATEGORY_COLORS = {
        '지브리':  '#FFFEF0',
        '뮤지컬':  '#FFF5F8',
        '강연':    '#F5FFF7',
        '김창옥':  '#F0F8FF',
        '기타':    '#FFFFFF',
    }

    def detect_category(campaigns):
        for c in campaigns:
            parts = c['name'].strip().split()
            for pos in [2, 3]:
                if len(parts) > pos and parts[pos] in CATEGORY_COLORS:
                    return parts[pos]
        name_str = ' '.join(c['name'] for c in campaigns)
        for cat in ['지브리', '뮤지컬', '강연', '김창옥']:
            if cat in name_str:
                return cat
        return '기타'

    # 모달용 HTML 사전 생성 (region → 캠페인 상세 HTML)
    import json as _json
    modal_contents = {}
    modal_data_json = ""  # f-string 밖에서 계산 (Python 3.9 백슬래시 제한 우회)
    region_sections = []
    for i, (region, data) in enumerate(regions_data.items()):
        color = colors[i % len(colors)]
        region_key = f"region_{i}"
        category = detect_category(data['campaigns'])

        # 모달 내용 (크리에이티브 + 캠페인 테이블)
        modal_contents[region_key] = f"""
        <div class="modal-region-title" style="border-left:4px solid {color}; padding-left:12px; margin-bottom:16px;">
            <span style="font-size:18px;font-weight:700">{region}</span>
            <span class="camp-count" style="margin-left:8px">{len(data['campaigns'])}개 캠페인</span>
        </div>
        {creative_strip(data['campaigns'])}
        <div class="table-wrap" style="margin-top:8px">
            <table>
                <thead>
                    <tr>
                        <th>캠페인명</th><th>시작일</th><th>노출수</th>
                        <th>클릭수</th><th>CTR</th><th>소진금액</th><th>도달수</th>
                    </tr>
                </thead>
                <tbody>{campaign_rows(data['campaigns'])}</tbody>
            </table>
        </div>"""

        # 카드 (헤더 + 요약만, 테이블 없음)
        region_sections.append(f"""
        <div class="region-card" onclick="openModal('{region_key}')" data-category="{category}" style="cursor:pointer;background:{CATEGORY_COLORS[category]}">
            <div class="region-header" style="border-left: 4px solid {color}">
                <div class="region-title">
                    <span class="region-dot" style="background:{color}"></span>
                    <h2>{region}</h2>
                    {('<span class="applicant-badge">👥 ' + fmt_number(data['campaigns'][0].get('applicants', 0)) + '명</span>') if data['campaigns'] and data['campaigns'][0].get('applicants') else ''}
                </div>
                <div class="region-summary">
                    <div class="summary-stat">
                        <span class="stat-label">총 노출</span>
                        <span class="stat-value">{fmt_number(data['total_impressions'])}</span>
                    </div>
                    <div class="summary-stat">
                        <span class="stat-label">총 DB</span>
                        <span class="stat-value">{fmt_number(data['campaigns'][0].get('applicants', 0)) if data['campaigns'] else '-'}</span>
                    </div>
                    <div class="summary-stat">
                        <span class="stat-label">평균 CTR</span>
                        <span class="stat-value">{fmt_pct(data['avg_ctr'])}</span>
                    </div>
                    <div class="summary-stat">
                        <span class="stat-label">총 소진</span>
                        <span class="stat-value">{fmt_currency(data['total_spend'])}</span>
                    </div>
                </div>
            </div>
            {progress_bar(data)}
            {platform_table(region, data)}
        </div>""")

    modal_data_json = _json.dumps(modal_contents, ensure_ascii=False).replace('</', '<\\/')

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Meta 광고 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.sheetjs.com/xlsx-0.20.0/package/dist/xlsx.full.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F0F2F5; color: #1C1E21; }}

  header {{ background: #1877F2; color: white; padding: 20px 32px; display: flex; align-items: center; justify-content: space-between; }}
  header h1 {{ font-size: 22px; font-weight: 700; }}
  header .subtitle {{ font-size: 13px; opacity: 0.85; margin-top: 2px; }}
  .date-badge {{ background: rgba(255,255,255,0.2); padding: 6px 14px; border-radius: 20px; font-size: 13px; }}
  .approval-link {{ background: #FFD54F; color: #E65100; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 700; text-decoration: none; }}
  .approval-link:hover {{ background: #FFC107; }}
  .excel-btn {{ background: #217346; color: white; border: none; padding: 6px 12px; border-radius: 16px; font-size: 12px; font-weight: 700; cursor: pointer; }}
  .excel-btn:hover {{ background: #1a5c38; }}
  .progress-wrap {{ padding: 8px 24px 6px; border-bottom: 1px solid #E4E6EB; cursor:default; }}
  .progress-top {{ display:flex; justify-content:space-between; margin-bottom:5px; }}
  .progress-label {{ font-size:11px; font-weight:700; color:#606770; text-transform:uppercase; letter-spacing:0.5px; }}
  .progress-pct {{ font-size:11px; font-weight:700; color:#1C1E21; }}
  .progress-bg {{ height:6px; background:#E4E6EB; border-radius:6px; overflow:hidden; }}
  .progress-fill {{ height:100%; border-radius:6px; transition:width 0.4s; }}
  .progress-detail {{ display:none; font-size:11px; color:#606770; margin-top:5px; padding-bottom:2px; }}
  .progress-wrap:hover .progress-detail {{ display:block; }}

  .upload-btn {{ background: #FF6F0F; color: white; padding: 6px 12px; border-radius: 16px; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }}
  .upload-btn:hover {{ background: #e05e00; }}
  .refresh-btn {{ background: rgba(255,255,255,0.2); color: white; border: none; padding: 6px 12px; border-radius: 16px; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }}
  .refresh-btn:hover {{ background: rgba(255,255,255,0.35); }}

  .container {{ max-width: 1280px; margin: 0 auto; padding: 28px 20px; }}

  .top-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 28px; }}
  .stat-card {{ background: white; border-radius: 12px; padding: 20px 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .stat-card .label {{ font-size: 12px; color: #606770; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }}
  .stat-card .value {{ font-size: 28px; font-weight: 700; margin-top: 6px; color: #1C1E21; }}
  .stat-card .sub {{ font-size: 12px; color: #606770; margin-top: 4px; }}

  .charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 28px; }}
  .chart-card {{ background: white; border-radius: 12px; padding: 20px 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .chart-card h3 {{ font-size: 14px; font-weight: 600; color: #606770; margin-bottom: 16px; }}

  .regions-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }}
  .region-card {{ background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); overflow: hidden; transition: box-shadow 0.15s; }}
  .region-card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.13); }}
  .card-detail-hint {{ text-align:right; font-size:12px; color:#1877F2; font-weight:600; padding:10px 20px; background:#F7F8FA; }}

  /* 모달 */
  .modal-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.45); z-index:1000; align-items:center; justify-content:center; }}
  .modal-overlay.open {{ display:flex !important; }}
  #assetsModal {{ z-index:1100; background:rgba(0,0,0,0.6); }}
  .modal-box {{ background:white; border-radius:16px; width:90%; max-width:900px; max-height:85vh; overflow-y:auto; box-shadow:0 8px 40px rgba(0,0,0,0.2); display:flex; flex-direction:column; }}
  .modal-header {{ display:flex; align-items:center; justify-content:space-between; padding:18px 24px; border-bottom:1px solid #E4E6EB; position:sticky; top:0; background:white; z-index:1; }}
  .modal-header h3 {{ font-size:16px; font-weight:700; }}
  .modal-close {{ background:none; border:none; font-size:22px; cursor:pointer; color:#606770; line-height:1; }}
  .modal-close:hover {{ color:#1C1E21; }}
  .modal-body {{ padding:20px 24px; }}
  .region-header {{ padding: 20px 24px; border-bottom: 1px solid #E4E6EB; }}
  .region-title {{ display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }}
  .region-dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
  .region-title h2 {{ font-size: 18px; font-weight: 700; }}
  .camp-count {{ background: #E4E6EB; color: #606770; font-size: 12px; padding: 2px 10px; border-radius: 10px; }}
  .applicant-badge {{ background: #E8F4FD; color: #1877F2; font-size: 13px; font-weight: 700; padding: 2px 10px; border-radius: 10px; }}
  .platform-table-wrap {{ padding: 12px 24px; border-bottom: 1px solid #E4E6EB; background: #FAFBFC; }}
  .platform-table {{ border-collapse: collapse; font-size: 12px; }}
  .platform-table th {{ color: #606770; font-weight: 600; padding: 4px 14px 4px 0; text-align: left; }}
  .platform-table td {{ padding: 4px 14px 4px 0; }}
  .plat-badge {{ padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; }}
  .region-summary {{ display: flex; gap: 32px; }}
  .summary-stat .stat-label {{ font-size: 11px; color: #606770; text-transform: uppercase; letter-spacing: 0.5px; }}
  .summary-stat .stat-value {{ font-size: 16px; font-weight: 700; margin-top: 2px; }}

  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{ background: #F7F8FA; font-size: 12px; color: #606770; font-weight: 600; padding: 12px 16px; text-align: left; white-space: nowrap; }}
  tbody tr {{ border-top: 1px solid #E4E6EB; }}
  tbody tr:hover {{ background: #F7F8FA; }}
  tbody td {{ padding: 12px 16px; font-size: 13px; }}
  .camp-name {{ font-weight: 500; max-width: 320px; }}

  .ctr-badge {{ padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
  .ctr-high {{ background: #E6F4EA; color: #137333; }}
  .ctr-mid {{ background: #FEF7E0; color: #945700; }}
  .ctr-low {{ background: #FCE8E6; color: #C5221F; }}

  .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 16px; color: #1C1E21; }}
  .applicant-count {{ font-weight: 700; color: #1877F2; }}
  .applicants-cell {{ white-space: nowrap; }}


  /* 승인 대기 섹션 */
  .approval-section {{ background: #FFF8E1; border: 1.5px solid #FFD54F; border-radius: 12px; padding: 20px 24px; margin-bottom: 24px; }}
  .approval-title {{ font-size: 15px; font-weight: 700; color: #E65100; margin-bottom: 14px; display: flex; align-items: center; gap: 10px; }}
  .approval-sub {{ font-size: 11px; font-weight: 400; color: #999; }}
  .approval-list {{ display: flex; flex-wrap: wrap; gap: 14px; }}
  .pending-card {{ background: white; border-radius: 10px; padding: 16px 18px; min-width: 220px; max-width: 260px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); display: flex; flex-direction: column; gap: 8px; }}
  .pending-name {{ font-weight: 700; font-size: 15px; color: #1C1E21; }}
  .pending-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .pending-meta span {{ font-size: 11px; background: #F0F2F5; padding: 2px 7px; border-radius: 8px; color: #444; }}
  .pending-title {{ font-size: 12px; color: #606770; }}
  .pending-assets {{ display: flex; gap: 6px; margin: 4px 0; }}
  .pending-thumb {{ width: 56px; height: 56px; object-fit: cover; border-radius: 6px; border: 1.5px solid #E4E6EB; }}
  .pending-thumb-empty {{ width: 56px; height: 56px; background: #E4E6EB; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 18px; }}
  .approve-btn {{ background: #1877F2; color: white; border: none; padding: 9px 0; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; width: 100%; margin-top: 4px; }}
  .approve-btn:hover:not(:disabled) {{ background: #1565C0; }}
  .approve-btn:disabled {{ background: #E4E6EB; color: #999; cursor: not-allowed; }}

  /* 크리에이티브 이미지 스트립 */
  .creative-strip {{ display: flex; gap: 14px; padding: 16px 24px; border-bottom: 1px solid #E4E6EB; flex-wrap: wrap; align-items: flex-start; background: #FAFBFC; }}
  .creative-item {{ display: flex; flex-direction: column; align-items: center; gap: 6px; }}
  .creative-thumb {{ width: 80px; height: 80px; object-fit: cover; border-radius: 8px; border: 2px solid #E4E6EB; display: block; }}
  .creative-thumb-empty {{ width: 80px; height: 80px; background: #E4E6EB; border-radius: 8px; }}
  .round-label {{ font-size: 12px; font-weight: 700; color: #1877F2; text-align: center; }}

  /* 캠페인 상태별 색상 */
  .camp-active td {{ background: #F0F7FF; }}
  .camp-active:hover td {{ background: #DDEEFF !important; }}
  .camp-paused td {{ background: #F7F7F7; color: #999; }}
  .camp-paused:hover td {{ background: #EEEEEE !important; }}
  .camp-paused .ctr-badge {{ opacity: 0.5; }}

  /* 캠페인 행 클릭 */
  .camp-row {{ cursor: pointer; transition: background 0.15s; }}
  .camp-row:hover {{ background: #EEF2FF !important; }}
  .camp-row.open {{ background: #EEF2FF; }}
  .expand-icon {{ display: inline-block; font-size: 10px; margin-right: 6px; transition: transform 0.2s; color: #606770; }}
  .camp-row.open .expand-icon {{ transform: rotate(90deg); }}

  /* 에셋 펼침 영역 */
  .ads-detail-row td {{ padding: 0; background: #F7F8FA; }}
  .ads-detail-inner {{ padding: 12px 16px 16px 36px; }}
  .ads-label {{ font-size: 11px; font-weight: 700; color: #606770; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .ads-table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .ads-table th {{ background: #F0F2F5; font-size: 11px; color: #606770; font-weight: 600; padding: 8px 12px; text-align: left; white-space: nowrap; }}
  .ads-table td {{ padding: 10px 12px; font-size: 12px; border-top: 1px solid #E4E6EB; vertical-align: middle; }}
  .ads-table tr:hover td {{ background: #F7F8FA; }}

  .ad-label {{ font-weight: 800; font-size: 13px; color: #1877F2; }}
  .ad-thumb {{ width: 48px; height: 48px; object-fit: cover; border-radius: 4px; background: #E4E6EB; }}
  .ad-thumb-placeholder {{ width: 48px; height: 48px; background: #E4E6EB; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 18px; }}
  .ad-name {{ max-width: 220px; font-weight: 500; }}

  /* 에셋 행 승자/기타 배경색 */
  .ad-row-winner td {{ background: #E8F4E8; }}
  .ad-row-other  td {{ background: #F7F7F7; color: #999; }}
  .ad-row-winner:hover td {{ background: #D6EDD6 !important; }}
  .ad-row-other:hover  td {{ background: #EEEEEE !important; }}

  /* ON/OFF 토글 */
  .toggle-btn {{ padding: 4px 12px; border-radius: 12px; border: none; cursor: pointer; font-size: 12px; font-weight: 700; transition: all 0.2s; }}
  .toggle-on  {{ background: #E6F4EA; color: #137333; }}
  .toggle-off {{ background: #F0F2F5; color: #606770; }}
  .toggle-btn:disabled {{ opacity: 0.5; cursor: wait; }}
  .toggle-btn.loading {{ opacity: 0.6; }}

  @media (max-width: 900px) {{
    .regions-grid {{ grid-template-columns: 1fr; }}
    .modal-box {{ width: 98%; max-height: 92vh; }}
  }}
  @media (max-width: 768px) {{
    .top-stats {{ grid-template-columns: repeat(2, 1fr); }}
    .charts-grid {{ grid-template-columns: 1fr; }}
    .region-summary {{ flex-wrap: wrap; gap: 16px; }}
  }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Meta 광고 대시보드</h1>
    <div class="subtitle">계정: {AD_ACCOUNT_ID} · 최근 30일 기준</div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
    <div class="date-badge">활성 캠페인 {totals['active_count']}개</div>
    <a href="approval.html" target="_blank" class="approval-link">📋 승인 대기</a>
    <button class="excel-btn" onclick="downloadExcel('event')">📥 행사별</button>
    <button class="excel-btn" onclick="downloadExcel('week')">📥 주차별</button>
    <button class="excel-btn" onclick="downloadExcel('month')">📥 월간</button>
    <form action="/upload" method="POST" enctype="multipart/form-data" style="margin:0">
      <label class="upload-btn" title="당근 CSV 파일 선택 후 자동 반영">
        🥕 당근 업로드
        <input type="file" name="csv" accept=".csv" onchange="this.form.submit()" style="display:none">
      </label>
    </form>
    <form action="/refresh" method="POST" style="margin:0">
      <button type="submit" class="refresh-btn">🔄 새로고침</button>
    </form>
  </div>
</header>

<div class="container">

  <div class="top-stats">
    <div class="stat-card">
      <div class="label">총 소진금액</div>
      <div class="value">{fmt_currency(totals['spend'])}</div>
      <div class="sub">활성 캠페인 합계</div>
    </div>
    <div class="stat-card">
      <div class="label">총 노출수</div>
      <div class="value">{fmt_number(totals['impressions'])}</div>
      <div class="sub">집행 중 캠페인</div>
    </div>
    <div class="stat-card">
      <div class="label">총 클릭수</div>
      <div class="value">{fmt_number(totals['clicks'])}</div>
      <div class="sub">링크 클릭 기준</div>
    </div>
    <div class="stat-card">
      <div class="label">평균 CTR</div>
      <div class="value">{fmt_pct(totals['avg_ctr'])}</div>
      <div class="sub">전체 캠페인 평균</div>
    </div>
  </div>

  <div class="charts-grid">
    <div class="chart-card">
      <h3>지역별 소진금액</h3>
      <canvas id="spendChart" height="220"></canvas>
    </div>
    <div class="chart-card">
      <h3>지역별 평균 CTR</h3>
      <canvas id="ctrChart" height="220"></canvas>
    </div>
  </div>

  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
    <div class="section-title" style="margin-bottom:0">지역별 캠페인 상세</div>
    <select id="categoryFilter" onchange="filterRegions(this.value)" style="padding:6px 12px;border-radius:8px;border:1px solid #E4E6EB;font-size:13px;color:#1C1E21;background:white;cursor:pointer;">
      <option value="전체">전체</option>
      <option value="지브리">지브리</option>
      <option value="뮤지컬">뮤지컬</option>
      <option value="강연">강연</option>
      <option value="김창옥">김창옥</option>
    </select>
  </div>

  <div class="regions-grid" id="regionsGrid">{''.join(region_sections)}</div>

</div>

<!-- 캠페인 상세 모달 -->
<div class="modal-overlay" id="regionModal" onclick="closeModal(event)">
  <div class="modal-box" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3 id="modalTitle">캠페인 상세</h3>
      <button class="modal-close" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-body" id="modalBody"></div>
  </div>
</div>

<!-- 에셋 모달 -->
<div class="modal-overlay" id="assetsModal" onclick="closeAssetsModal(event)">
  <div class="modal-box" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3 id="assetsModalTitle">에셋 성과</h3>
      <button class="modal-close" onclick="closeAssetsModal()">✕</button>
    </div>
    <div class="modal-body" id="assetsModalBody"></div>
  </div>
</div>

<script id="ads-data" type="application/json">{ads_data_json}</script>
<script id="excel-data" type="application/json">{excel_json}</script>
<script id="modal-data" type="application/json">{modal_data_json}</script>

<script>
const ACCESS_TOKEN = "{ACCESS_TOKEN}";
const ADS_DATA = JSON.parse(document.getElementById('ads-data').textContent);
const EXCEL_DATA = JSON.parse(document.getElementById('excel-data').textContent);
const MODAL_DATA = JSON.parse(document.getElementById('modal-data').textContent);

// ── 모달 열기/닫기 ───────────────────────────────────────────────
function openModal(regionKey) {{
  document.getElementById('modalBody').innerHTML = MODAL_DATA[regionKey] || '';
  document.getElementById('regionModal').classList.add('open');
  document.body.style.overflow = 'hidden';
}}
function closeModal(e) {{
  if (e && e.target !== document.getElementById('regionModal') && e.type === 'click') return;
  document.getElementById('regionModal').classList.remove('open');
  document.body.style.overflow = '';
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') {{ closeModal(); closeAssetsModal(); }} }});

// ── 엑셀 다운로드 ────────────────────────────────────────────────
function downloadExcel(mode) {{
  let rows = [...EXCEL_DATA];
  let filename = '광고성과_행사별.xlsx';
  let sheetData = [];

  if (mode === 'event') {{
    filename = '광고성과_행사별.xlsx';
    sheetData = rows;
  }} else if (mode === 'week') {{
    filename = '광고성과_주차별.xlsx';
    const weekMap = {{}};
    rows.forEach(r => {{
      const d = new Date(r['공연일']);
      if (isNaN(d)) return;
      const week = `${{d.getFullYear()}}-W${{String(Math.ceil((d.getDate() + new Date(d.getFullYear(), d.getMonth(), 1).getDay()) / 7)).padStart(2,'0')}}`;
      const key = week + '_' + r['플랫폼'];
      if (!weekMap[key]) weekMap[key] = {{ '주차': week, '플랫폼': r['플랫폼'], '소진금액': 0, '노출수': 0, '클릭수': 0, '신청자수': 0 }};
      weekMap[key]['소진금액'] += r['소진금액'];
      weekMap[key]['노출수'] += r['노출수'];
      weekMap[key]['클릭수'] += r['클릭수'];
      if (r['신청자수']) weekMap[key]['신청자수'] += Number(r['신청자수']) || 0;
    }});
    sheetData = Object.values(weekMap).map(r => ({{ ...r, 'CTR': r['노출수'] ? (r['클릭수']/r['노출수']*100).toFixed(2)+'%' : '-' }}));
  }} else if (mode === 'month') {{
    filename = '광고성과_월간.xlsx';
    const monthMap = {{}};
    rows.forEach(r => {{
      const d = new Date(r['공연일']);
      if (isNaN(d)) return;
      const month = `${{d.getFullYear()}}-${{String(d.getMonth()+1).padStart(2,'0')}}`;
      const key = month + '_' + r['플랫폼'];
      if (!monthMap[key]) monthMap[key] = {{ '월': month, '플랫폼': r['플랫폼'], '소진금액': 0, '노출수': 0, '클릭수': 0, '신청자수': 0 }};
      monthMap[key]['소진금액'] += r['소진금액'];
      monthMap[key]['노출수'] += r['노출수'];
      monthMap[key]['클릭수'] += r['클릭수'];
      if (r['신청자수']) monthMap[key]['신청자수'] += Number(r['신청자수']) || 0;
    }});
    sheetData = Object.values(monthMap).map(r => ({{ ...r, 'CTR': r['노출수'] ? (r['클릭수']/r['노출수']*100).toFixed(2)+'%' : '-' }}));
  }}

  const ws = XLSX.utils.json_to_sheet(sheetData);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, '광고성과');
  XLSX.writeFile(wb, filename);
}}


// ── 캠페인 승인 (PAUSED → ACTIVE) ──────────────────────────────
async function approveCampaign(campaignId, btn) {{
  if (!confirm('이 캠페인을 ACTIVE로 전환하시겠습니까?')) return;
  btn.disabled = true;
  btn.textContent = '처리 중...';
  try {{
    const body = new URLSearchParams({{ status: 'ACTIVE', access_token: ACCESS_TOKEN }});
    const resp = await fetch(`https://graph.facebook.com/{API_VERSION}/${{campaignId}}`, {{ method: 'POST', body }});
    const result = await resp.json();
    if (result.success) {{
      btn.textContent = '✅ 집행 시작됨';
      btn.style.background = '#E6F4EA';
      btn.style.color = '#137333';
      btn.closest('.pending-card').style.opacity = '0.5';
    }} else {{
      btn.textContent = '❌ 실패';
      btn.disabled = false;
      alert('오류: ' + (result.error?.message || JSON.stringify(result)));
    }}
  }} catch(e) {{
    btn.textContent = '❌ 실패';
    btn.disabled = false;
    alert('오류: ' + e.message);
  }}
}}

// ── 캠페인 클릭 → 에셋 모달 팝업 ────────────────────────────────
function toggleAds(row) {{
  const cid = row.dataset.campaignId;
  const ads = ADS_DATA[cid] || [];
  const campName = row.querySelector('.camp-name').textContent.replace('▶', '').trim();
  document.getElementById('assetsModalTitle').textContent = campName;
  document.getElementById('assetsModalBody').innerHTML = renderAdsTable(ads);
  document.getElementById('assetsModal').classList.add('open');
  document.body.style.overflow = 'hidden';
}}

function closeAssetsModal(e) {{
  if (e && e.target !== document.getElementById('assetsModal')) return;
  document.getElementById('assetsModal').classList.remove('open');
}}

// ── 에셋 테이블 렌더링 ──────────────────────────────────────────
function renderAdsTable(ads) {{
  if (!ads.length) return '<p style="color:#606770;font-size:13px;padding:8px 0">에셋 데이터 없음</p>';

  const labels = ['A','B','C','D','E','F','G','H'];
  const withData = ads.filter(a => a.insights?.data?.[0]);
  const sorted = [...withData].sort((a,b) =>
    parseFloat(b.insights.data[0].ctr||0) - parseFloat(a.insights.data[0].ctr||0));
  const winnerId = sorted.length > 1 ? sorted[0].id : null;

  const rows = ads.map((ad, i) => {{
    const ins = ad.insights?.data?.[0];
    const ctr  = ins ? parseFloat(ins.ctr  || 0) : null;
    const cpm  = ins ? parseFloat(ins.cpm  || 0) : null;
    const spend= ins ? parseFloat(ins.spend|| 0) : null;
    const thumb = ad.creative?.thumbnail_url;

    const rowClass = winnerId
      ? (ad.id === winnerId ? 'ad-row-winner' : 'ad-row-other')
      : '';

    const isOn = ad.status === 'ACTIVE';
    const thumbHtml = thumb
      ? `<img class="ad-thumb" src="${{thumb}}" onerror="this.style.display='none'">`
      : `<div class="ad-thumb-placeholder">🖼</div>`;

    return `<tr class="${{rowClass}}">
      <td><span class="ad-label">${{labels[i]||i+1}}</span></td>
      <td>${{thumbHtml}}</td>
      <td class="ad-name">${{ad.name}}</td>
      <td>${{ctr !== null ? ctr.toFixed(2)+'%' : '-'}}</td>
      <td>${{cpm !== null ? '₩'+Math.round(cpm).toLocaleString() : '-'}}</td>
      <td>${{spend !== null ? '₩'+Math.round(spend).toLocaleString() : '-'}}</td>
      <td>
        <button class="toggle-btn ${{isOn ? 'toggle-on' : 'toggle-off'}}"
          data-ad-id="${{ad.id}}"
          data-status="${{ad.status}}"
          onclick="event.stopPropagation(); toggleAdStatus(this)">
          ${{isOn ? 'ON' : 'OFF'}}
        </button>
      </td>
    </tr>`;
  }}).join('');

  return `<table class="ads-table">
    <thead><tr>
      <th></th><th>미리보기</th><th>에셋명</th>
      <th>CTR</th><th>CPM</th><th>소진</th><th>상태</th>
    </tr></thead>
    <tbody>${{rows}}</tbody>
  </table>`;
}}

// ── ON/OFF 토글 → Meta API 호출 ──────────────────────────────────
async function toggleAdStatus(btn) {{
  const adId = btn.dataset.adId;
  const current = btn.dataset.status;
  const next = current === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';

  btn.disabled = true;
  btn.classList.add('loading');

  try {{
    const body = new URLSearchParams({{ status: next, access_token: ACCESS_TOKEN }});
    const resp = await fetch(`https://graph.facebook.com/{API_VERSION}/${{adId}}`, {{
      method: 'POST', body
    }});
    const result = await resp.json();

    if (result.success) {{
      btn.dataset.status = next;
      btn.textContent = next === 'ACTIVE' ? 'ON' : 'OFF';
      btn.className = `toggle-btn ${{next === 'ACTIVE' ? 'toggle-on' : 'toggle-off'}}`;
    }} else {{
      alert('변경 실패: ' + (result.error?.message || JSON.stringify(result)));
    }}
  }} catch(e) {{
    alert('오류: ' + e.message);
  }}

  btn.disabled = false;
  btn.classList.remove('loading');
}}

// ── 카테고리 필터 ────────────────────────────────────────────────
function filterRegions(cat) {{
  document.querySelectorAll('#regionsGrid .region-card').forEach(card => {{
    card.style.display = (cat === '전체' || card.dataset.category === cat) ? '' : 'none';
  }});
}}

// ── 차트 ────────────────────────────────────────────────────────
const labels = {chart_labels};
const colors = {chart_colors};

new Chart(document.getElementById('spendChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: {chart_spend}, backgroundColor: colors, borderRadius: 6 }}] }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{ ticks: {{ callback: v => '₩'+v.toLocaleString() }}, grid: {{ color: '#F0F2F5' }} }},
      x: {{ grid: {{ display: false }} }}
    }}
  }}
}});

new Chart(document.getElementById('ctrChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: {chart_ctr_avg}, backgroundColor: colors, borderRadius: 6 }}] }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      y: {{ ticks: {{ callback: v => v+'%' }}, grid: {{ color: '#F0F2F5' }} }},
      x: {{ grid: {{ display: false }} }}
    }}
  }}
}});
</script>

</body>
</html>"""


def campaign_event_date(name):
    """캠페인명 '260612 성남...' → date(2026, 6, 12). 파싱 실패 시 None."""
    m = re.match(r"26(\d{2})(\d{2})", name.strip())
    if m:
        try:
            return date_cls(2026, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def main():
    today = date_cls.today()

    print("Meta 캠페인 조회 중 (ACTIVE + PAUSED)...")
    all_campaigns = get_all_active_campaigns()
    print(f"  전체 {len(all_campaigns)}개 조회됨.")
    campaigns = [c for c in all_campaigns
                 if campaign_event_date(c["name"]) and campaign_event_date(c["name"]) >= today]
    print(f"  오늘({today}) 이후 행사 캠페인: {len(campaigns)}개")

    # ── 타 플랫폼 캠페인 수집 ──────────────────────────────────────
    from platforms.kakao_api import get_campaigns as kakao_fn
    from platforms.naver_api import get_campaigns as naver_fn
    from platforms.google_api import get_campaigns as google_fn

    other_campaigns = []
    for fn, label in [(kakao_fn, "카카오"), (naver_fn, "네이버"), (google_fn, "구글")]:
        try:
            cs = fn(today)
            print(f"  [{label}] {len(cs)}개")
            other_campaigns.extend(cs)
        except Exception as e:
            print(f"  [{label}] 조회 실패: {e}")

    # region → platform → {spend, impressions, clicks, reach, ctr} 집계
    platform_by_region = defaultdict(lambda: defaultdict(lambda: {"spend": 0.0, "impressions": 0, "clicks": 0, "reach": 0, "ctr": 0.0}))
    for c in other_campaigns:
        region = extract_region(c["name"])
        p = c["platform"]
        platform_by_region[region][p]["spend"] += c["spend"]
        platform_by_region[region][p]["impressions"] += c["impressions"]
        platform_by_region[region][p]["clicks"] += c["clicks"]

    print("에셋(광고) 데이터 조회 중...")
    all_ads = get_all_active_ads()
    # 오늘 이후 캠페인 ID 목록 기준으로 ads 필터링
    upcoming_campaign_ids = {c["id"] for c in campaigns}
    ads = [a for a in all_ads if a.get("campaign_id") in upcoming_campaign_ids]
    print(f"{len(ads)}개 광고 발견 (오늘 이후 행사).")

    print("여유톡 신청자 수 조회 중...")
    applicant_counts = get_applicant_counts()  # {(6, 9): 1005, ...}

    print("노션 좌석수 조회 중...")
    from notion_client_helper import get_seat_by_date
    seat_by_date = get_seat_by_date()  # {(6, 9): 3200, ...}

    ads_by_campaign = defaultdict(list)
    for ad in ads:
        ads_by_campaign[ad["campaign_id"]].append(ad)

    regions_data = defaultdict(lambda: {
        "campaigns": [],
        "total_spend": 0,
        "total_impressions": 0,
        "total_clicks": 0,
        "total_reach": 0,
        "avg_ctr": 0,
    })

    for campaign in campaigns:
        raw = campaign.get("insights", {}).get("data", [])
        insights = raw[0] if raw else None
        region = extract_region(campaign["name"])

        if insights:
            spend = float(insights.get("spend", 0))
            impressions = int(insights.get("impressions", 0))
            clicks = int(insights.get("clicks", 0))
            ctr = float(insights.get("ctr", 0))
            reach = int(insights.get("reach", 0))
        else:
            spend = impressions = clicks = ctr = reach = 0

        date_key = campaign_date_key(campaign["name"])
        applicants = applicant_counts.get(date_key, 0)
        if date_key and date_key in seat_by_date:
            regions_data[region]["seat_count"] = seat_by_date[date_key]

        created = campaign.get("created_time", "")[:10]  # "2026-05-06T..." → "2026-05-06"

        regions_data[region]["campaigns"].append({
            "id": campaign["id"],
            "name": campaign["name"],
            "status": campaign["status"],
            "objective": campaign.get("objective", "-"),
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "reach": reach,
            "applicants": applicants,
            "created": created,
        })
        regions_data[region]["total_spend"] += spend
        regions_data[region]["total_impressions"] += impressions
        regions_data[region]["total_clicks"] += clicks
        regions_data[region]["total_reach"] += reach

    for region, data in regions_data.items():
        active = [c for c in data["campaigns"] if c["impressions"] > 0]
        data["avg_ctr"] = sum(c["ctr"] for c in active) / len(active) if active else 0

    def region_date_key(campaigns):
        for c in campaigns:
            m = re.match(r"26(\d{2})(\d{2})", c["name"])
            if m:
                return (int(m.group(1)), int(m.group(2)))
        return (99, 99)

    # ── 당근 CSV 통합 ──────────────────────────────────────────────
    from platforms.danggeun_api import get_from_csv as danggeun_csv
    base_dir = os.path.dirname(os.path.abspath(__file__))
    danggeun_data = danggeun_csv(base_dir)

    if danggeun_data:
        # 날짜 키 → 지역명 매핑
        date_to_region = {region_date_key(d["campaigns"]): region
                          for region, d in regions_data.items()}
        for date_key, stats in danggeun_data.items():
            region = date_to_region.get(date_key)
            if region:
                platform_by_region[region]["danggeun"]["spend"] += stats["spend"]
                platform_by_region[region]["danggeun"]["impressions"] += stats["impressions"]
                platform_by_region[region]["danggeun"]["clicks"] += stats["clicks"]
                platform_by_region[region]["danggeun"]["reach"] += stats["reach"]

    sorted_regions = dict(sorted(
        regions_data.items(),
        key=lambda x: region_date_key(x[1]["campaigns"])
    ))

    all_camps_with_data = [c for rd in regions_data.values() for c in rd["campaigns"] if c["impressions"] > 0]
    totals = {
        "active_count": len(campaigns),
        "spend": sum(rd["total_spend"] for rd in regions_data.values()),
        "impressions": sum(rd["total_impressions"] for rd in regions_data.values()),
        "clicks": sum(rd["total_clicks"] for rd in regions_data.values()),
        "avg_ctr": sum(c["ctr"] for c in all_camps_with_data) / len(all_camps_with_data) if all_camps_with_data else 0,
    }

    print("\nHTML 대시보드 생성 중...")
    html = build_html(sorted_regions, totals, dict(ads_by_campaign), dict(platform_by_region))

    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("완료! dashboard.html 저장됨")

    approval = build_approval_html()
    with open("approval.html", "w", encoding="utf-8") as f:
        f.write(approval)
    print("완료! approval.html 저장됨")


if __name__ == "__main__":
    main()

import requests
import json
import re
import os
from datetime import date as date_cls, datetime, timezone
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from scrape_applicants import login as yy_login, get_active_events, count_applicants

load_dotenv()

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "act_810493558680773")
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
            "id,name,status,campaign_id,created_time,"
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


def build_html(regions_data, totals, ads_by_campaign, platform_by_region=None, pending_campaigns=None, dry_run_alerts=None, upload_complete=None, pending_upload=None, upload_log=None):
    colors = ["#4F86C6", "#E07B54", "#5BAD6F", "#9B5EA2", "#D4A843",
              "#E05C87", "#43A8A8", "#8B7355", "#6B7A8D", "#C96B6B"]

    # ── 업로드 실패 알람 (자동 업로드 실패한 건만 표시) ─────────────────
    pending = pending_upload or []
    if pending:
        chips = "".join(
            f'<span class="notif-chip">{p.get("공연명","")}</span>'
            for p in pending
        )
        notif_block_html = f"""
  <div class="task-block notif-block">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span class="notif-dot"></span>
        <span class="task-label" style="background:#C62828;color:white;border-radius:6px;padding:2px 10px;font-size:12px;font-weight:700;">업로드 실패</span>
        <span class="task-badge" style="background:#FFEBEE;color:#C62828;">{len(pending)}건</span>
        {chips}
      </div>
      <a href="/ad-setup" class="notif-goto-btn" style="background:#C62828;">⚙️ 세팅탭에서 수동 업로드 →</a>
    </div>
  </div>"""
    else:
        notif_block_html = ""

    # ── A작업: 업로드완료 → ACTIVE 전환 대기 ────────────────────────────
    a_camps = upload_complete or []

    def a_card(p):
        age_str = "/".join(p.get("연령대") or ["40대", "50대"])
        cid = p.get("캠페인ID", "")
        pid = p.get("page_id", "")
        return f"""<div class="pending-card">
            <div class="pending-name">{p['공연명']}</div>
            <div class="pending-meta">
                <span>📅 {p.get('공연일','')}</span>
                <span>📍 {p.get('지역','')}</span>
                <span>💰 ₩{int(p.get('일예산',0)):,}/일</span>
                <span>👥 {age_str} {p.get('성별','여성')}</span>
            </div>
            <div class="pending-camp-id">Meta ID: {cid}</div>
            <button class="approve-btn"
                onclick="activateCampaign('{cid}', '{pid}', this)">
                🚀 ACTIVE 전환
            </button>
        </div>"""

    if a_camps:
        a_task_html = f"""
  <div class="task-block">
    <div class="task-block-header">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <span class="task-label a-label">A작업</span>
        <span class="task-title-text">업로드완료 → ACTIVE 전환 대기</span>
        <span class="task-badge a-badge">{len(a_camps)}건</span>
      </div>
      <span class="task-desc">Meta에 업로드된 캠페인을 검토 후 집행 시작하세요</span>
    </div>
    <div class="pending-list">{"".join(a_card(p) for p in a_camps)}</div>
  </div>"""
    else:
        a_task_html = """
  <div class="task-block task-block-empty">
    <span class="task-label a-label">A작업</span>
    <span class="task-title-text">업로드완료 → ACTIVE 전환 대기</span>
    <span class="task-empty-msg">승인 대기 캠페인 없음</span>
  </div>"""

    # ── B작업: 48시간 에셋 최적화 알람 ──────────────────────────────────
    alerts = dry_run_alerts or []
    if alerts:
        def alarm_card(alert):
            camp_name = alert["campaign_name"]
            winner = alert["winner"]
            losers = alert["loser_ids"]
            loser_ids_json = json.dumps([l["id"] for l in losers])
            winner_row = f"""<div class="alarm-asset alarm-winner">
                ✅ <b>{winner['name']}</b>
                <span class="alarm-stat">₩{int(winner['spend']):,}</span>
                <span class="alarm-stat">CTR {winner['ctr']:.2f}%</span>
                <span class="alarm-keep">유지</span>
            </div>"""
            loser_rows = "".join(f"""<div class="alarm-asset alarm-loser">
                ⏸ {l['name']}
                <span class="alarm-stat">₩{int(l['spend']):,}</span>
                <span class="alarm-stat">CTR {l['ctr']:.2f}%</span>
                <span class="alarm-cut">끌 예정</span>
            </div>""" for l in losers)
            return f"""<div class="alarm-card">
                <div class="alarm-card-title">{camp_name}</div>
                <div class="alarm-assets">{winner_row}{loser_rows}</div>
                <button class="alarm-exec-btn" onclick="executeCut({loser_ids_json}, this)">이 캠페인 실행</button>
            </div>"""

        all_loser_ids = json.dumps([l["id"] for a in alerts for l in a["loser_ids"]])
        b_task_html = f"""
  <div class="task-block">
    <div class="task-block-header">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <span class="task-label b-label">B작업</span>
        <span class="task-title-text">48시간 에셋 최적화</span>
        <span class="task-badge b-badge">{len(alerts)}건 대기</span>
      </div>
      <button class="alarm-all-btn" onclick="executeAllCuts({all_loser_ids})">전체 실행</button>
    </div>
    <div class="alarm-cards">{"".join(alarm_card(a) for a in alerts)}</div>
  </div>"""
    else:
        b_task_html = """
  <div class="task-block task-block-empty">
    <span class="task-label b-label">B작업</span>
    <span class="task-title-text">48시간 에셋 최적화</span>
    <span class="task-empty-msg">현재 48시간 이상 경과한 에셋 없음</span>
  </div>"""

    # ── 업로드 이력 섹션 ─────────────────────────────────────────────
    log_entries = (upload_log or [])[:30]

    def log_row(entry):
        titles = " / ".join(filter(None, [
            entry.get("광고제목A", ""),
            entry.get("광고제목B", ""),
            entry.get("광고제목C", ""),
        ])) or "제목 없음"
        차수 = entry.get("차수", "")
        차수_colors = {
            "1차": "#1877F2", "2차": "#E65100", "3차": "#137333",
            "4차": "#9B5EA2", "5차": "#D4A843", "영상": "#E05C87", "잠재": "#43A8A8",
        }
        chip_color = 차수_colors.get(차수, "#606770")
        return f"""<div class="ulog-row">
      <span class="ulog-time">{entry.get("uploaded_at","")}</span>
      <span class="ulog-name">{entry.get("공연명","")}</span>
      <span class="ulog-chip" style="background:{chip_color}">{차수}</span>
      <span class="ulog-title">{titles}</span>
    </div>"""

    if log_entries:
        log_rows_html = "".join(log_row(e) for e in log_entries)
        upload_log_html = f"""
  <div class="upload-log-block">
    <div class="upload-log-header">
      <span class="task-label" style="background:#1877F2;color:white;">업로드 이력</span>
      <span class="task-title-text">Meta에 올라간 광고</span>
      <span class="task-badge" style="background:#E7F3FF;color:#1877F2;">{len(log_entries)}건</span>
    </div>
    <div class="ulog-list">{log_rows_html}</div>
  </div>"""
    else:
        upload_log_html = ""

    workflow_section_html = f"""
  <div class="workflow-container">
{notif_block_html}
{a_task_html}
{b_task_html}
{upload_log_html}
  </div>"""

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

    def detect_month(campaigns):
        for c in campaigns:
            key = campaign_date_key(c['name'])
            if key:
                return str(key[0])
        return '0'

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
        month = detect_month(data['campaigns'])

        # 공연일 + 요일
        _WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
        _edate = campaign_event_date(data['campaigns'][0]['name']) if data['campaigns'] else None
        event_date_label = f"{_edate.month}/{_edate.day}({_WEEKDAYS[_edate.weekday()]})" if _edate else ""

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
        venue_name = data.get("venue_name") or region
        region_sections.append(f"""
        <div class="region-card" id="card-{region_key}" onclick="openModal('{region_key}')" data-category="{category}" data-month="{month}" data-label="{venue_name}" style="cursor:pointer;background:{CATEGORY_COLORS[category]};border-left:4px solid {color}">
            <button class="card-close-btn" onclick="hideCard('{region_key}',event)" title="숨기기">×</button>
            <div class="region-header">
                <div class="region-title">
                    <span class="region-dot" style="background:{color}"></span>
                    <h2>{(' <span class="event-date-label">' + event_date_label + '</span> ') if event_date_label else ''}{venue_name}</h2>
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
  .region-card {{ background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); overflow: hidden; transition: box-shadow 0.15s; position: relative; }}
  .region-card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.13); }}
  .card-close-btn {{ position:absolute; top:8px; right:8px; width:20px; height:20px; background:rgba(0,0,0,0.18); border:none; border-radius:50%; color:white; font-size:13px; line-height:1; cursor:pointer; display:flex; align-items:center; justify-content:center; z-index:10; padding:0; }}
  .card-close-btn:hover {{ background:rgba(0,0,0,0.45); }}
  .hidden-bar {{ background:#fff3cd; border-bottom:1px solid #ffc107; padding:8px 32px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:13px; color:#856404; }}
  .hidden-chip {{ background:#ffc107; border:none; border-radius:12px; padding:3px 10px; font-size:12px; cursor:pointer; color:#333; font-weight:600; }}
  .hidden-chip:hover {{ background:#e0a800; }}
  .confirm-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.45); z-index:9000; align-items:center; justify-content:center; }}
  .confirm-overlay.open {{ display:flex; }}
  .confirm-box {{ background:white; border-radius:14px; padding:28px 32px; max-width:320px; width:90%; box-shadow:0 8px 32px rgba(0,0,0,0.18); text-align:center; }}
  .confirm-box p {{ font-size:15px; font-weight:600; color:#1C1E21; margin-bottom:20px; line-height:1.5; }}
  .confirm-btns {{ display:flex; gap:10px; justify-content:center; }}
  .confirm-ok {{ background:#1877F2; color:white; border:none; border-radius:8px; padding:10px 28px; font-size:14px; font-weight:700; cursor:pointer; }}
  .confirm-ok:hover {{ background:#1464d8; }}
  .confirm-cancel {{ background:#E4E6EB; color:#1C1E21; border:none; border-radius:8px; padding:10px 28px; font-size:14px; font-weight:600; cursor:pointer; }}
  .confirm-cancel:hover {{ background:#d0d2d6; }}
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
  .event-date-label {{ font-size: 18px; font-weight: 700; color: #1C1E21; margin-right: 4px; }}
  .camp-count {{ background: #E4E6EB; color: #606770; font-size: 12px; padding: 2px 10px; border-radius: 10px; }}
  .applicant-badge {{ background: #E8F4FD; color: #1877F2; font-size: 13px; font-weight: 700; padding: 2px 10px; border-radius: 10px; }}
  .platform-table-wrap {{ padding: 12px 24px; border-bottom: 1px solid #E4E6EB; }}
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

  /* 월 셀 */
  .month-cell {{ text-align:center; padding:6px 4px; border-radius:6px; font-size:12px; font-weight:600; cursor:pointer; color:#606770; transition:all 0.15s; }}
  .month-cell:hover {{ background:#EEF2FF; color:#1877F2; }}
  .month-cell.selected {{ background:#1877F2; color:white; }}

  /* 커스텀 드롭다운 */
  .cust-dropdown {{ position:relative; }}
  .cust-dropdown-btn {{ background:white; border:1px solid #E4E6EB; padding:5px 12px; border-radius:8px; font-size:13px; font-weight:600; cursor:pointer; color:#1C1E21; display:flex; align-items:center; gap:6px; }}
  .cust-dropdown-btn:hover {{ border-color:#1877F2; }}
  .cust-dropdown-menu {{ display:none; position:absolute; top:calc(100% + 4px); right:0; background:white; border:1px solid #E4E6EB; border-radius:8px; box-shadow:0 4px 16px rgba(0,0,0,0.12); min-width:120px; z-index:500; overflow:hidden; }}
  .cust-dropdown-menu.open {{ display:block; }}
  .cust-dropdown-item {{ padding:9px 16px; font-size:13px; cursor:pointer; color:#1C1E21; }}
  .cust-dropdown-item:hover {{ background:#F0F2F5; }}
  .cust-dropdown-item.selected {{ font-weight:700; color:#1877F2; background:#EEF2FF; }}
  .applicant-count {{ font-weight: 700; color: #1877F2; }}
  .applicants-cell {{ white-space: nowrap; }}


  /* 워크플로우 (A/B 작업) 섹션 */
  .workflow-container {{ display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px; }}
  .notif-block {{ border-left: 4px solid #E65100; }}
  .notif-dot {{ width: 9px; height: 9px; background: #E65100; border-radius: 50%; display: inline-block; flex-shrink: 0; animation: notif-pulse 1.5s ease-in-out infinite; }}
  @keyframes notif-pulse {{ 0%,100% {{ opacity:1; transform:scale(1); }} 50% {{ opacity:0.4; transform:scale(0.8); }} }}
  .notif-chip {{ font-size: 12px; background: #FFF3E0; color: #E65100; padding: 2px 10px; border-radius: 10px; white-space: nowrap; }}
  .notif-goto-btn {{ background: #E65100; color: white; text-decoration: none; padding: 8px 18px; border-radius: 8px; font-size: 13px; font-weight: 700; white-space: nowrap; display: inline-block; }}
  .notif-goto-btn:hover {{ background: #BF360C; }}
  .task-block {{ background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); padding: 20px 24px; }}
  .task-block-empty {{ display: flex; align-items: center; gap: 10px; }}
  .task-block-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }}
  .task-label {{ font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 6px; }}
  .a-label {{ background: #E3F2FD; color: #1565C0; }}
  .b-label {{ background: #FFF3E0; color: #E65100; }}
  .task-title-text {{ font-size: 15px; font-weight: 700; color: #1C1E21; }}
  .task-badge {{ font-size: 12px; font-weight: 700; padding: 2px 10px; border-radius: 12px; }}
  .a-badge {{ background: #E3F2FD; color: #1565C0; }}
  .b-badge {{ background: #FFE0B2; color: #E65100; }}
  .task-desc {{ font-size: 12px; color: #90949C; }}
  .task-empty-msg {{ font-size: 13px; color: #90949C; }}
  .pending-list {{ display: flex; flex-wrap: wrap; gap: 14px; }}
  .pending-card {{ background: #F7F8FA; border-radius: 10px; padding: 16px 18px; min-width: 200px; flex: 1; border: 1px solid #E4E6EB; display: flex; flex-direction: column; gap: 8px; }}
  .pending-name {{ font-weight: 700; font-size: 14px; color: #1C1E21; }}
  .pending-meta {{ display: flex; flex-wrap: wrap; gap: 5px; }}
  .pending-meta span {{ font-size: 11px; background: white; padding: 2px 7px; border-radius: 8px; border: 1px solid #E4E6EB; color: #444; }}
  .pending-camp-id {{ font-size: 10px; color: #90949C; font-family: monospace; word-break: break-all; }}
  .approve-btn {{ background: #1877F2; color: white; border: none; padding: 9px 0; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; width: 100%; margin-top: 4px; }}
  .approve-btn:hover:not(:disabled) {{ background: #1565C0; }}
  .approve-btn:disabled {{ background: #E4E6EB; color: #999; cursor: not-allowed; }}
  /* 알람 카드 (B작업) */
  .alarm-cards {{ display: flex; flex-wrap: wrap; gap: 14px; }}
  .alarm-card {{ background: #F7F8FA; border-radius: 10px; padding: 16px 18px; min-width: 260px; flex: 1; border: 1px solid #E4E6EB; }}
  .alarm-card-title {{ font-size: 13px; font-weight: 700; color: #1C1E21; margin-bottom: 10px; }}
  .alarm-assets {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }}
  .alarm-asset {{ font-size: 12px; padding: 7px 10px; border-radius: 7px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
  .alarm-winner {{ background: #E6F4EA; color: #1B5E20; }}
  .alarm-loser {{ background: #FFF3E0; color: #6D4C41; }}
  .alarm-stat {{ font-size: 11px; color: #606770; margin-left: 4px; }}
  .alarm-keep {{ margin-left: auto; font-size: 11px; font-weight: 700; color: #137333; background: #C8E6C9; padding: 2px 8px; border-radius: 8px; }}
  .alarm-cut {{ margin-left: auto; font-size: 11px; font-weight: 700; color: #BF360C; background: #FFE0B2; padding: 2px 8px; border-radius: 8px; }}
  .alarm-exec-btn {{ background: #1877F2; color: white; border: none; padding: 8px 0; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; width: 100%; }}
  .alarm-exec-btn:hover {{ background: #1565C0; }}
  .alarm-all-btn {{ background: #E65100; color: white; border: none; padding: 7px 18px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 700; }}
  .alarm-all-btn:hover {{ background: #BF360C; }}

  /* 업로드 이력 */
  .upload-log-block {{ background: white; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 12px; }}
  .upload-log-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
  .ulog-list {{ display: flex; flex-direction: column; gap: 6px; }}
  .ulog-row {{ display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: #F7F8FA; border-radius: 8px; flex-wrap: wrap; }}
  .ulog-time {{ font-size: 11px; color: #90949C; white-space: nowrap; min-width: 110px; }}
  .ulog-name {{ font-size: 13px; font-weight: 700; color: #1C1E21; min-width: 120px; }}
  .ulog-chip {{ font-size: 11px; font-weight: 700; color: white; padding: 2px 8px; border-radius: 12px; white-space: nowrap; }}
  .ulog-title {{ font-size: 12px; color: #444; flex: 1; }}

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
    <a href="/ad-setup" class="approval-link" style="background:#E7F3FF;color:#1877F2;">⚙️ 메타광고세팅</a>
    <a href="/leads" class="approval-link" style="background:#E8F5E9;color:#137333;">👥 잠재고객</a>
    <button class="excel-btn" onclick="downloadExcel('event')">📥 행사별</button>
    <button class="excel-btn" onclick="downloadExcel('week')">📥 주차별</button>
    <button class="excel-btn" onclick="downloadExcel('month')">📥 월간</button>
    <form action="/upload" method="POST" enctype="multipart/form-data" style="margin:0">
      <label class="upload-btn" title="당근 CSV 파일 선택 후 자동 반영">
        🥕 당근 업로드
        <input type="file" name="csv" accept=".csv" onchange="this.form.submit()" style="display:none">
      </label>
    </form>
    <form action="/refresh" method="POST" style="margin:0" onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='호출 중...'">
      <button type="submit" class="refresh-btn">📡 메타호출</button>
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

{workflow_section_html}

  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:10px;">
    <div class="section-title" style="margin-bottom:0">지역별 캠페인 상세</div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <!-- 월별 드롭다운 -->
      <div class="cust-dropdown" id="monthDropdown">
        <button class="cust-dropdown-btn" onclick="toggleMonthDropdown()">
          <span id="monthLabel">기간</span> ▾
        </button>
        <div class="cust-dropdown-menu" id="monthMenu" style="min-width:176px;">
          <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border-bottom:1px solid #E4E6EB;">
            <span style="font-size:11px;font-weight:700;color:#606770;">2026년</span>
            <div class="month-cell selected" id="monthAllCell" onclick="pickMonth('0',this)" style="padding:3px 10px;font-size:11px;">전체</div>
          </div>
          <div style="padding:8px;display:grid;grid-template-columns:repeat(3,1fr);gap:4px;">
            <div class="month-cell" onclick="pickMonth('1',this)">1월</div>
            <div class="month-cell" onclick="pickMonth('2',this)">2월</div>
            <div class="month-cell" onclick="pickMonth('3',this)">3월</div>
            <div class="month-cell" onclick="pickMonth('4',this)">4월</div>
            <div class="month-cell" onclick="pickMonth('5',this)">5월</div>
            <div class="month-cell" onclick="pickMonth('6',this)">6월</div>
            <div class="month-cell" onclick="pickMonth('7',this)">7월</div>
            <div class="month-cell" onclick="pickMonth('8',this)">8월</div>
            <div class="month-cell" onclick="pickMonth('9',this)">9월</div>
            <div class="month-cell" onclick="pickMonth('10',this)">10월</div>
            <div class="month-cell" onclick="pickMonth('11',this)">11월</div>
            <div class="month-cell" onclick="pickMonth('12',this)">12월</div>
          </div>
        </div>
      </div>
      <!-- 카테고리 커스텀 드롭다운 -->
      <div class="cust-dropdown" id="catDropdown">
        <button class="cust-dropdown-btn" onclick="toggleDropdown()">
          <span id="catLabel">분류</span> ▾
        </button>
        <div class="cust-dropdown-menu" id="catMenu">
          <div class="cust-dropdown-item" onclick="setCategory('전체',this)">전체</div>
          <div class="cust-dropdown-item" onclick="setCategory('지브리',this)">지브리</div>
          <div class="cust-dropdown-item" onclick="setCategory('뮤지컬',this)">뮤지컬</div>
          <div class="cust-dropdown-item" onclick="setCategory('강연',this)">강연</div>
          <div class="cust-dropdown-item" onclick="setCategory('김창옥',this)">김창옥</div>
        </div>
      </div>
    </div>
  </div>

  <div class="confirm-overlay" id="hideConfirmOverlay">
    <div class="confirm-box">
      <p>광고를 대시보드에서<br>끄시겠습니까?</p>
      <div class="confirm-btns">
        <button class="confirm-cancel" onclick="closeHideConfirm()">취소</button>
        <button class="confirm-ok" id="hideConfirmOk">확인</button>
      </div>
    </div>
  </div>
  <div class="hidden-bar" id="hiddenBar" style="display:none">
    <span>숨긴 행사:</span>
    <div id="hiddenList" style="display:flex;gap:6px;flex-wrap:wrap"></div>
    <span style="font-size:11px;color:#999;margin-left:4px">(클릭하면 다시 표시)</span>
  </div>
  <div class="regions-grid" id="regionsGrid">{''.join(region_sections)}</div>

  <div class="charts-grid" style="margin-top:32px">
    <div class="chart-card">
      <h3>지역별 소진금액</h3>
      <canvas id="spendChart" height="220"></canvas>
    </div>
    <div class="chart-card">
      <h3>지역별 평균 CTR</h3>
      <canvas id="ctrChart" height="220"></canvas>
    </div>
  </div>

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


// ── A작업: 업로드완료 캠페인 ACTIVE 전환 (백엔드 경유 → 노션 상태도 업데이트) ──
async function activateCampaign(campaignId, pageId, btn) {{
  if (!confirm('이 캠페인을 ACTIVE로 전환하시겠습니까? 집행 시작 후 노션 상태가 "집행중"으로 변경됩니다.')) return;
  btn.disabled = true;
  btn.textContent = '처리 중...';
  try {{
    const resp = await fetch('/api/campaign/activate', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ campaign_id: campaignId, page_id: pageId }})
    }});
    const result = await resp.json();
    if (result.success) {{
      btn.textContent = '✅ 집행 시작됨';
      btn.style.background = '#E6F4EA';
      btn.style.color = '#137333';
      btn.closest('.pending-card').style.opacity = '0.5';
    }} else {{
      btn.textContent = '❌ 실패';
      btn.disabled = false;
      alert('오류: ' + (result.error || JSON.stringify(result)));
    }}
  }} catch(e) {{
    btn.textContent = '❌ 실패';
    btn.disabled = false;
    alert('오류: ' + e.message);
  }}
}}

// ── 캠페인 승인 (approval.html 전용, PAUSED → ACTIVE) ──────────────────────────────
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

// ── 자동화 알람 — 에셋 컷 실행 ───────────────────────────────────
async function pauseAd(adId) {{
  const body = new URLSearchParams({{ status: 'PAUSED', access_token: ACCESS_TOKEN }});
  const resp = await fetch(`https://graph.facebook.com/{API_VERSION}/${{adId}}`, {{ method: 'POST', body }});
  const result = await resp.json();
  if (!result.success) throw new Error(result.error?.message || JSON.stringify(result));
}}

async function executeCut(loserIds, btn) {{
  if (!confirm(`${{loserIds.length}}개 에셋을 PAUSED 처리하시겠습니까?`)) return;
  btn.disabled = true;
  btn.textContent = '처리 중...';
  try {{
    await Promise.all(loserIds.map(id => pauseAd(id)));
    btn.textContent = '✅ 완료';
    btn.style.background = '#137333';
    btn.closest('.alarm-card').querySelectorAll('.alarm-loser').forEach(el => {{
      el.style.opacity = '0.4';
      el.querySelector('.alarm-cut').textContent = '완료';
    }});
  }} catch(e) {{
    btn.textContent = '❌ 실패';
    btn.disabled = false;
    alert('오류: ' + e.message);
  }}
}}

async function executeAllCuts(allLoserIds) {{
  if (!confirm(`전체 ${{allLoserIds.length}}개 에셋을 PAUSED 처리하시겠습니까?`)) return;
  document.querySelectorAll('.alarm-exec-btn').forEach(btn => btn.click && (btn.disabled = true));
  try {{
    await Promise.all(allLoserIds.map(id => pauseAd(id)));
    document.querySelectorAll('.alarm-loser').forEach(el => {{
      el.style.opacity = '0.4';
      const cut = el.querySelector('.alarm-cut');
      if (cut) cut.textContent = '완료';
    }});
    document.querySelectorAll('.alarm-exec-btn').forEach(btn => {{
      btn.textContent = '✅ 완료';
      btn.style.background = '#137333';
    }});
  }} catch(e) {{
    alert('오류: ' + e.message);
    document.querySelectorAll('.alarm-exec-btn').forEach(btn => btn.disabled = false);
  }}
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

// ── 필터 ─────────────────────────────────────────────────────────
let _cat = '전체', _month = '0';

function applyFilters() {{
  document.querySelectorAll('#regionsGrid .region-card').forEach(card => {{
    const catOk = _cat === '전체' || card.dataset.category === _cat;
    const monOk = _month === '0' || card.dataset.month === _month;
    card.style.display = (catOk && monOk) ? '' : 'none';
  }});
}}

function setCategory(cat, el) {{
  _cat = cat;
  document.getElementById('catLabel').textContent = cat === '전체' ? '분류' : cat;
  document.querySelectorAll('.cust-dropdown-item').forEach(i => i.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('catMenu').classList.remove('open');
  applyFilters();
}}

function pickMonth(month, el) {{
  _month = month;
  document.getElementById('monthLabel').textContent = month === '0' ? '기간' : month + '월';
  document.querySelectorAll('.month-cell').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('monthMenu').classList.remove('open');
  applyFilters();
}}

function toggleMonthDropdown() {{
  document.getElementById('monthMenu').classList.toggle('open');
  document.getElementById('catMenu').classList.remove('open');
}}

function toggleDropdown() {{
  document.getElementById('catMenu').classList.toggle('open');
  document.getElementById('monthMenu').classList.remove('open');
}}

document.addEventListener('click', e => {{
  if (!document.getElementById('catDropdown').contains(e.target))
    document.getElementById('catMenu').classList.remove('open');
  if (!document.getElementById('monthDropdown').contains(e.target))
    document.getElementById('monthMenu').classList.remove('open');
}});

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

// ── 카드 숨기기 / 복원 ──────────────────────────────────────────
let _pendingHideKey = null;

function hideCard(regionKey, event) {{
  event.stopPropagation();
  event.preventDefault();
  _pendingHideKey = regionKey;
  document.getElementById('hideConfirmOverlay').classList.add('open');
  document.getElementById('hideConfirmOk').onclick = function() {{
    closeHideConfirm();
    const card = document.getElementById('card-' + _pendingHideKey);
    if (!card) return;
    card.style.display = 'none';
    const saved = JSON.parse(localStorage.getItem('hiddenCards') || '{{}}');
    saved[_pendingHideKey] = card.dataset.label || _pendingHideKey;
    localStorage.setItem('hiddenCards', JSON.stringify(saved));
    renderHiddenBar();
  }};
}}

function closeHideConfirm() {{
  document.getElementById('hideConfirmOverlay').classList.remove('open');
  _pendingHideKey = null;
}}

function showCard(regionKey) {{
  const card = document.getElementById('card-' + regionKey);
  if (card) card.style.display = '';
  const saved = JSON.parse(localStorage.getItem('hiddenCards') || '{{}}');
  delete saved[regionKey];
  localStorage.setItem('hiddenCards', JSON.stringify(saved));
  renderHiddenBar();
}}

function renderHiddenBar() {{
  const saved = JSON.parse(localStorage.getItem('hiddenCards') || '{{}}');
  const bar = document.getElementById('hiddenBar');
  const list = document.getElementById('hiddenList');
  const keys = Object.keys(saved);
  if (keys.length === 0) {{ bar.style.display = 'none'; return; }}
  bar.style.display = '';
  list.innerHTML = keys.map(k =>
    `<button class="hidden-chip" onclick="showCard('${{k}}')">${{saved[k]}} ✕</button>`
  ).join('');
}}

(function initHiddenCards() {{
  const saved = JSON.parse(localStorage.getItem('hiddenCards') || '{{}}');
  Object.keys(saved).forEach(k => {{
    const card = document.getElementById('card-' + k);
    if (card) card.style.display = 'none';
  }});
  renderHiddenBar();
}})();
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
    seat_by_date, venue_by_date = get_seat_by_date()  # {(6, 9): 3200, ...}, {(6, 9): "아산 온양관광호텔", ...}

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
        if date_key and date_key in venue_by_date and not regions_data[region].get("venue_name"):
            regions_data[region]["venue_name"] = venue_by_date[date_key]

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

    # ── 48시간 에셋 컷 dry-run 계산 ──────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    dry_run_alerts = []
    for camp_id, camp_ads in ads_by_campaign.items():
        camp = next((c for c in campaigns if c["id"] == camp_id), None)
        if not camp:
            continue
        eligible = []
        for ad in camp_ads:
            created_str = ad.get("created_time", "")
            if not created_str:
                continue
            created_dt = datetime.fromisoformat(re.sub(r'([+-])(\d{2})(\d{2})$', r'\1\2:\3', created_str.replace("Z", "+00:00")))
            hours = (now_utc - created_dt).total_seconds() / 3600
            if hours < 48:
                continue
            ins = (ad.get("insights") or {}).get("data", [{}])
            ins = ins[0] if ins else {}
            eligible.append({
                "id": ad["id"],
                "name": ad.get("name", ad["id"]),
                "spend": float(ins.get("spend", 0)),
                "ctr": float(ins.get("ctr", 0)),
                "status": ad.get("status", ""),
            })
        active_eligible = [a for a in eligible if a["status"] == "ACTIVE"]
        if len(active_eligible) < 2:
            continue
        active_eligible.sort(key=lambda x: x["spend"], reverse=True)
        winner = active_eligible[0]
        losers = active_eligible[1:]
        dry_run_alerts.append({
            "campaign_name": camp["name"],
            "winner": winner,
            "loser_ids": losers,
        })
    print(f"  → dry-run 알람 {len(dry_run_alerts)}건")

    from notion_client_helper import query_campaigns as _qc, parse_campaign as _parse

    pending_upload_campaigns = []

    # 노션 '업로드완료' 캠페인 조회 (A작업 목록)
    try:
        upload_complete_pages = _qc(filter_status="업로드완료")
        upload_complete_campaigns = [_parse(p) for p in upload_complete_pages]
        print(f"  → 업로드완료 캠페인 {len(upload_complete_campaigns)}건 (A작업 대기)")
    except Exception as e:
        print(f"  → 노션 업로드완료 조회 실패: {e}")
        upload_complete_campaigns = []

    # 업로드 이력 로그 읽기
    upload_log = []
    upload_log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "upload_log.json")
    try:
        with open(upload_log_file, encoding="utf-8") as f:
            upload_log = json.load(f)
        print(f"  → 업로드 이력 {len(upload_log)}건")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    print("\nHTML 대시보드 생성 중...")
    html = build_html(sorted_regions, totals, dict(ads_by_campaign), dict(platform_by_region), dry_run_alerts=dry_run_alerts, upload_complete=upload_complete_campaigns, pending_upload=pending_upload_campaigns, upload_log=upload_log)

    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("완료! dashboard.html 저장됨")

    approval = build_approval_html()
    with open("approval.html", "w", encoding="utf-8") as f:
        f.write(approval)
    print("완료! approval.html 저장됨")


if __name__ == "__main__":
    main()

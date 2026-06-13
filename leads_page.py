"""잠재고객 관리 페이지 — Meta Lead API fetch + 데이터 가공."""
import os
import re
import io
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()


def _env():
    token = os.getenv("META_ACCESS_TOKEN")
    version = os.getenv("META_API_VERSION", "v20.0")
    raw = os.getenv("META_AD_ACCOUNT_ID", "")
    account = f"act_{raw}" if not raw.startswith("act_") else raw
    return token, version, account


# ─── 데이터 정제 ─────────────────────────────────────────────

def _normalize_date(value: str) -> str:
    if not value:
        return ""
    v = value.strip()
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', v)
    if m:
        month, day, year = m.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return v


def _normalize_name(value: str) -> tuple:
    if not value:
        return "", False
    # 괄호 내용 제거: 지언(29세) → 지언
    cleaned = re.sub(r'[（(][^）)]*[）)]', '', value).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # 수정필요 플래그: 자모 분리 또는 영어만
    has_jamo = bool(re.search(r'[ㄱ-ㅎㅏ-ㅣ]', cleaned))
    is_foreign = bool(re.match(r'^[A-Za-z\s\-\.]+$', cleaned)) and len(cleaned) > 0
    needs_review = has_jamo or is_foreign
    return cleaned, needs_review


def _normalize_gender(_value: str) -> str:
    return "여"


def _parse_fields(field_data: list) -> dict:
    out = {}
    for f in field_data:
        key = f.get("name", "").lower().replace(" ", "_")
        vals = f.get("values", [])
        out[key] = vals[0] if vals else ""
    return out


def _process_lead(lead: dict) -> dict:
    fields = _parse_fields(lead.get("field_data", []))
    name, needs_review = _normalize_name(fields.get("full_name", ""))
    return {
        "platform": lead.get("platform", fields.get("platform", "facebook")).lower(),
        "full_name": name,
        "needs_review": needs_review,
        "date_of_birth": _normalize_date(fields.get("date_of_birth", "")),
        "phone_number": fields.get("phone_number", fields.get("phone", "")),
        "gender": _normalize_gender(fields.get("gender", "")),
        "created_time": lead.get("created_time", "")[:10],
    }


# ─── Meta API ─────────────────────────────────────────────────

def fetch_all_leads() -> list:
    token, version, account = _env()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # 광고계정의 모든 리드폼 조회
    forms = []
    url = f"https://graph.facebook.com/{version}/{account}/leadgen_forms"
    cursor = None
    while True:
        params = {"fields": "id,name", "access_token": token, "limit": 100}
        if cursor:
            params["after"] = cursor
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        forms.extend(data.get("data", []))
        paging = data.get("paging", {})
        if not paging.get("next"):
            break
        cursor = paging.get("cursors", {}).get("after")
        if not cursor:
            break

    # 각 폼에서 어제까지의 리드 수집
    all_leads = []
    for form in forms:
        form_id = form["id"]
        lead_url = f"https://graph.facebook.com/{version}/{form_id}/leads"
        lcursor = None
        while True:
            lparams = {
                "fields": "field_data,created_time,platform",
                "access_token": token,
                "limit": 100,
            }
            if lcursor:
                lparams["after"] = lcursor
            lr = requests.get(lead_url, params=lparams, timeout=15)
            lr.raise_for_status()
            ldata = lr.json()
            batch = ldata.get("data", [])
            for lead in batch:
                if lead.get("created_time", "")[:10] <= yesterday:
                    all_leads.append(_process_lead(lead))
            if not ldata.get("paging", {}).get("next"):
                break
            lcursor = ldata.get("paging", {}).get("cursors", {}).get("after")
            if not lcursor:
                break

    return all_leads


def generate_excel(leads: list) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "잠재고객"
    ws.append(["platform", "full_name", "date_of_birth", "phone_number", "gender"])
    for lead in leads:
        ws.append([
            lead.get("platform", ""),
            lead.get("full_name", ""),
            lead.get("date_of_birth", ""),
            lead.get("phone_number", ""),
            lead.get("gender", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ─── HTML 페이지 ──────────────────────────────────────────────

def build_leads_html() -> str:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>잠재고객 관리</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F0F2F5; min-height: 100vh; }}
  header {{ background: #1877F2; color: white; padding: 18px 32px; display: flex; align-items: center; justify-content: space-between; }}
  header h1 {{ font-size: 20px; font-weight: 700; }}
  .back-link {{ color: white; text-decoration: none; font-size: 14px; font-weight: 600; opacity: 0.9; }}
  .back-link:hover {{ opacity: 1; }}
  .toolbar {{ padding: 20px 32px 0; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  .fetch-btn {{ background: #1877F2; color: white; border: none; padding: 10px 24px; border-radius: 20px; font-size: 14px; font-weight: 700; cursor: pointer; }}
  .fetch-btn:hover {{ background: #1565C0; }}
  .fetch-btn:disabled {{ background: #90CAF9; cursor: wait; }}
  .dl-btn {{ background: #137333; color: white; border: none; padding: 10px 24px; border-radius: 20px; font-size: 14px; font-weight: 700; cursor: pointer; display: none; }}
  .dl-btn:hover {{ background: #0D5226; }}
  .dl-btn:disabled {{ background: #81C995; cursor: wait; }}
  .status-txt {{ font-size: 13px; color: #606770; }}
  .table-wrap {{ margin: 20px 32px 40px; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead {{ background: #F5F7FA; }}
  th {{ padding: 12px 16px; text-align: left; font-weight: 700; color: #1C1E21; border-bottom: 2px solid #E4E6EB; white-space: nowrap; }}
  td {{ padding: 10px 16px; border-bottom: 1px solid #F0F2F5; color: #1C1E21; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #F7F9FC; }}
  .badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; white-space: nowrap; }}
  .badge-review {{ background: #FFF3E0; color: #E65100; margin-left: 6px; }}
  .badge-insta {{ background: #F3E5F5; color: #7B1FA2; }}
  .badge-fb {{ background: #E3F2FD; color: #1565C0; }}
  .empty-state {{ text-align: center; padding: 60px; color: #606770; font-size: 14px; }}
  .spinner {{ display: none; width: 20px; height: 20px; border: 3px solid #E4E6EB; border-top-color: #1877F2; border-radius: 50%; animation: spin 0.8s linear infinite; flex-shrink: 0; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
<body>
<header>
  <a href="/" class="back-link">← 대시보드</a>
  <h1>잠재고객 관리</h1>
  <div style="font-size:13px;opacity:0.8;">{yesterday} 까지</div>
</header>

<div class="toolbar">
  <button class="fetch-btn" id="fetchBtn" onclick="fetchLeads()">불러오기</button>
  <button class="dl-btn" id="dlBtn" onclick="downloadExcel()">엑셀 다운로드</button>
  <div class="spinner" id="spinner"></div>
  <span class="status-txt" id="statusTxt"></span>
</div>

<div class="table-wrap">
  <div class="empty-state" id="emptyState">불러오기 버튼을 눌러 데이터를 가져오세요.</div>
  <table id="leadsTable" style="display:none;">
    <thead>
      <tr>
        <th>플랫폼</th>
        <th>이름</th>
        <th>생년월일</th>
        <th>전화번호</th>
        <th>성별</th>
      </tr>
    </thead>
    <tbody id="leadsBody"></tbody>
  </table>
</div>

<script>
async function fetchLeads() {{
  const btn = document.getElementById('fetchBtn');
  const spinner = document.getElementById('spinner');
  const statusTxt = document.getElementById('statusTxt');
  btn.disabled = true;
  spinner.style.display = 'block';
  statusTxt.textContent = '데이터 불러오는 중...';
  try {{
    const resp = await fetch('/api/leads');
    if (!resp.ok) {{
      const err = await resp.json().catch(() => ({{}}));
      throw new Error(err.error || resp.statusText);
    }}
    const data = await resp.json();
    renderTable(data);
    statusTxt.textContent = `총 ${{data.length}}명`;
    document.getElementById('dlBtn').style.display = 'inline-block';
  }} catch(e) {{
    statusTxt.textContent = '오류: ' + e.message;
  }} finally {{
    btn.disabled = false;
    spinner.style.display = 'none';
  }}
}}

function renderTable(data) {{
  const tbody = document.getElementById('leadsBody');
  const table = document.getElementById('leadsTable');
  const empty = document.getElementById('emptyState');
  if (!data.length) {{
    empty.textContent = '데이터가 없습니다.';
    empty.style.display = 'block';
    table.style.display = 'none';
    return;
  }}
  tbody.innerHTML = data.map(r => {{
    const platBadge = r.platform === 'instagram'
      ? '<span class="badge badge-insta">Instagram</span>'
      : '<span class="badge badge-fb">Facebook</span>';
    const reviewBadge = r.needs_review
      ? '<span class="badge badge-review">수정필요</span>' : '';
    return `<tr>
      <td>${{platBadge}}</td>
      <td>${{r.full_name}}${{reviewBadge}}</td>
      <td>${{r.date_of_birth}}</td>
      <td>${{r.phone_number}}</td>
      <td>${{r.gender}}</td>
    </tr>`;
  }}).join('');
  empty.style.display = 'none';
  table.style.display = 'table';
}}

async function downloadExcel() {{
  const btn = document.getElementById('dlBtn');
  btn.disabled = true;
  btn.textContent = '생성 중...';
  try {{
    const resp = await fetch('/api/leads/download');
    if (!resp.ok) throw new Error('다운로드 실패');
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = '잠재고객_' + new Date().toISOString().slice(0, 10) + '.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  }} catch(e) {{
    alert('오류: ' + e.message);
  }} finally {{
    btn.disabled = false;
    btn.textContent = '엑셀 다운로드';
  }}
}}
</script>
</body>
</html>"""

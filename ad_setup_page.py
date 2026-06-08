"""메타광고세팅 페이지 — Notion 메타 광고 오토세팅 DB 뷰어 + 업로드 실행."""
import os
import re
import requests
from dotenv import load_dotenv
from notion_client_helper import parse_campaign

load_dotenv()

STATUS_ORDER = ["대기", "업로드완료", "집행중"]
STATUS_COLOR = {
    "대기":      "#E65100",
    "업로드완료": "#1565C0",
    "집행중":    "#137333",
}
STATUS_BG = {
    "대기":      "#FFF3E0",
    "업로드완료": "#E3F2FD",
    "집행중":    "#E6F4EA",
}
STATUS_ICON = {
    "대기": "⏳",
    "업로드완료": "📤",
    "집행중": "▶",
}


def _drive_thumb(url: str) -> str:
    """Google Drive 공유 URL → 직접 이미지 URL."""
    if not url:
        return ""
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url) or \
        re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        fid = m.group(1)
        # lh3 형식이 브라우저에서 더 잘 로드됨
        return f"https://lh3.googleusercontent.com/d/{fid}"
    return ""


def _fetch_all() -> list:
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    DB_ID = os.getenv("CAMPAIGN_NOTION_DB_ID")
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    pages, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{DB_ID}/query",
            headers=headers, json=body, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return pages


def _asset_block(label: str, url: str, title: str, body: str) -> str:
    thumb = _drive_thumb(url)
    img_id = f"img-{label}-{abs(hash(url or label))}"

    if thumb:
        img_html = f"""<div class="asset-img-wrap">
          <img id="{img_id}" src="{thumb}" class="asset-img" alt="에셋{label}"
               onerror="onImgErr(this)">
          <div class="asset-img-overlay">
            <a href="{url}" target="_blank" class="img-open-btn">원본 열기 ↗</a>
          </div>
        </div>"""
    else:
        img_html = '<div class="asset-img-empty"><span class="img-empty-icon">🖼</span><span>URL 없음</span></div>'

    title_html = (
        f'<div class="asset-title">{title}</div>'
        if title else '<div class="asset-no-val">제목 미입력</div>'
    )

    if body:
        body_id = f"body-{label}-{abs(hash(body[:20]))}"
        body_html = f"""<div class="asset-body-wrap">
          <div class="asset-body" id="{body_id}">{body}</div>
          <button class="body-toggle-btn" onclick="toggleBody('{body_id}', this)">더보기 ▾</button>
        </div>"""
    else:
        body_html = '<div class="asset-no-val">본문 미입력</div>'

    return f"""<div class="asset-col">
      <div class="asset-lbl lbl-{label.lower()}">{label}</div>
      {img_html}
      {title_html}
      {body_html}
    </div>"""


def _camp_card(p: dict) -> str:
    status = p.get("상태") or "대기"
    page_id = p.get("page_id", "")
    color = STATUS_COLOR.get(status, "#606770")
    bg = STATUS_BG.get(status, "#F0F2F5")
    icon = STATUS_ICON.get(status, "")

    age_str = "/".join(p.get("연령대") or []) or "-"
    budget = f"₩{int(p.get('일예산', 0)):,}" if p.get("일예산") else "-"
    landing = p.get("랜딩URL") or ""

    upload_btn = (
        f'<button class="upload-btn" onclick="uploadCampaign(\'{page_id}\', this)">↺ 수동 업로드 재시도</button>'
        if status == "대기" else ""
    )

    meta_id_html = ""
    if p.get("캠페인ID"):
        meta_id_html = f'<div class="meta-id">Meta ID: <code>{p["캠페인ID"]}</code></div>'

    landing_html = (
        f'<a href="{landing}" target="_blank" class="landing-link">🔗 {landing[:60]}{"…" if len(landing)>60 else ""}</a>'
        if landing else '<span class="no-val">랜딩 URL 없음</span>'
    )

    has_content = any(
        p.get(f"에셋{l}") or p.get(f"광고제목{l}") or p.get(f"광고본문{l}")
        for l in ["A", "B", "C"]
    )
    if has_content:
        cols = "".join(
            _asset_block(l, p.get(f"에셋{l}", ""), p.get(f"광고제목{l}", ""), p.get(f"광고본문{l}", ""))
            for l in ["A", "B", "C"]
        )
        assets_html = f'<div class="assets-grid">{cols}</div>'
    else:
        assets_html = '<div class="no-asset">에셋 · 제목 · 본문 미입력</div>'

    return f"""<div class="camp-card" id="card-{page_id}" style="border-top:3px solid {color}">
  <div class="card-header">
    <div class="card-title-row">
      <span class="camp-name">{p.get('공연명') or '(제목 없음)'}</span>
      <span class="status-chip" style="background:{bg};color:{color}">{icon} {status}</span>
    </div>
    {upload_btn}
  </div>
  <div class="meta-row">
    <span>📅 공연일 <b>{p.get('공연일') or '-'}</b></span>
    <span>📢 광고시작 <b>{p.get('광고시작일') or '-'}</b></span>
    <span>📍 <b>{p.get('지역') or '-'}</b></span>
    <span>🔢 <b>{p.get('차수') or '1차'}</b></span>
    <span>💰 <b>{budget}/일</b></span>
    <span>👥 <b>{age_str} {p.get('성별') or '여성'}</b></span>
  </div>
  <div class="landing-row">{landing_html}</div>
  {meta_id_html}
  {assets_html}
</div>"""


def build_ad_setup_html() -> str:
    notion_error = None
    all_camps = []
    try:
        pages = _fetch_all()
        all_camps = [parse_campaign(p) for p in pages]
    except Exception as e:
        notion_error = str(e)

    groups: dict = {s: [] for s in STATUS_ORDER}
    for c in all_camps:
        groups.setdefault(c.get("상태") or "대기", []).append(c)

    if notion_error:
        body_html = f'<div class="error-box">⚠️ Notion 연결 오류: {notion_error}</div>'
    elif not all_camps:
        body_html = '<div class="empty-state">노션 DB에 등록된 캠페인이 없습니다.</div>'
    else:
        body_html = ""
        all_statuses = STATUS_ORDER + [s for s in groups if s not in STATUS_ORDER and groups[s]]
        for status in all_statuses:
            camps = groups.get(status, [])
            if not camps:
                continue
            color = STATUS_COLOR.get(status, "#606770")
            bg = STATUS_BG.get(status, "#F0F2F5")
            icon = STATUS_ICON.get(status, "")
            body_html += f"""<div class="section">
  <div class="section-head">
    <span class="status-chip" style="background:{bg};color:{color};font-size:13px;padding:4px 14px;">{icon} {status}</span>
    <span class="section-count">{len(camps)}건</span>
  </div>
  {"".join(_camp_card(c) for c in camps)}
</div>"""

    total = len(all_camps)
    summary = "".join(
        f'<span style="background:{STATUS_BG[s]};color:{STATUS_COLOR[s]};padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700;">'
        f'{STATUS_ICON[s]} {s} {len(groups.get(s,[]))}건</span>'
        for s in STATUS_ORDER if groups.get(s)
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>메타광고세팅</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #F0F2F5; color: #1C1E21; font-size: 14px; }}

/* ── 헤더 ── */
.top-bar {{ background: #1877F2; color: white; padding: 14px 24px;
            display: flex; align-items: center; justify-content: space-between; }}
.top-bar h1 {{ font-size: 17px; font-weight: 700; }}
.back-btn {{ color: white; text-decoration: none; background: rgba(255,255,255,.18);
             padding: 6px 14px; border-radius: 20px; font-size: 12px; }}

/* ── 레이아웃 ── */
.wrap {{ max-width: 980px; margin: 0 auto; padding: 22px 18px; }}

/* ── 요약 바 ── */
.summary-bar {{ background: white; border-radius: 10px; padding: 12px 18px;
                margin-bottom: 22px; display: flex; align-items: center;
                gap: 10px; flex-wrap: wrap; box-shadow: 0 1px 4px rgba(0,0,0,.07); }}
.summary-bar .total {{ font-weight: 700; font-size: 14px; }}

/* ── 섹션 ── */
.section {{ margin-bottom: 30px; }}
.section-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }}
.section-count {{ font-size: 13px; color: #606770; }}
.status-chip {{ font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 20px; white-space: nowrap; }}

/* ── 캠페인 카드 ── */
.camp-card {{ background: white; border-radius: 12px; padding: 18px 20px;
              margin-bottom: 14px; box-shadow: 0 1px 6px rgba(0,0,0,.08); }}

.card-header {{ display: flex; align-items: flex-start; justify-content: space-between;
                gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }}
.card-title-row {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; flex: 1; }}
.camp-name {{ font-size: 16px; font-weight: 700; }}

.upload-btn {{ background: #E65100; color: white; border: none; padding: 9px 20px;
               border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 700;
               white-space: nowrap; flex-shrink: 0; }}
.upload-btn:hover {{ background: #BF360C; }}
.upload-btn:disabled {{ background: #ccc; color: #888; cursor: not-allowed; }}

/* ── 메타 정보 ── */
.meta-row {{ display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }}
.meta-row span {{ font-size: 12px; color: #555; background: #F0F2F5;
                  padding: 4px 10px; border-radius: 8px; }}
.meta-row b {{ color: #1C1E21; }}

.landing-row {{ margin-bottom: 10px; font-size: 13px; }}
.landing-link {{ color: #1877F2; text-decoration: none; word-break: break-all; }}
.landing-link:hover {{ text-decoration: underline; }}
.no-val {{ color: #BCC0C4; font-size: 12px; }}

.meta-id {{ font-size: 11px; color: #90949C; margin-bottom: 10px; }}
.meta-id code {{ background: #F0F2F5; padding: 1px 5px; border-radius: 4px; font-size: 11px; }}

/* ── 에셋 그리드 ── */
.assets-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
                margin-top: 16px; padding-top: 16px;
                border-top: 1px solid #E4E6EB; }}
@media (max-width: 660px) {{ .assets-grid {{ grid-template-columns: 1fr; }} }}

.asset-col {{ display: flex; flex-direction: column; gap: 10px; }}

/* 에셋 라벨 */
.asset-lbl {{ display: inline-flex; align-items: center; justify-content: center;
              width: 28px; height: 28px; border-radius: 50%; font-size: 13px;
              font-weight: 800; color: white; }}
.lbl-a {{ background: #1877F2; }}
.lbl-b {{ background: #E65100; }}
.lbl-c {{ background: #137333; }}

/* 이미지 */
.asset-img-wrap {{ position: relative; border-radius: 10px; overflow: hidden;
                   background: #F0F2F5; aspect-ratio: 1/1; }}
.asset-img {{ width: 100%; height: 100%; object-fit: cover; display: block;
              transition: opacity .2s; }}
.asset-img-wrap:hover .asset-img {{ opacity: 0.82; }}
.asset-img-overlay {{ position: absolute; bottom: 0; left: 0; right: 0;
                      background: linear-gradient(transparent, rgba(0,0,0,.55));
                      padding: 20px 10px 8px; opacity: 0;
                      transition: opacity .2s; }}
.asset-img-wrap:hover .asset-img-overlay {{ opacity: 1; }}
.img-open-btn {{ color: white; font-size: 11px; text-decoration: none; font-weight: 600; }}

.asset-img-empty {{ aspect-ratio: 1/1; background: #F0F2F5; border-radius: 10px;
                    display: flex; flex-direction: column; align-items: center;
                    justify-content: center; gap: 6px; color: #BBBFC4; }}
.img-empty-icon {{ font-size: 30px; }}
.asset-img-empty span {{ font-size: 11px; }}

/* 에셋 제목 */
.asset-title {{ font-size: 13px; font-weight: 700; color: #1C1E21;
                line-height: 1.45; word-break: break-word; }}
.asset-no-val {{ font-size: 12px; color: #BCC0C4; font-style: italic; }}

/* 에셋 본문 - 접기/펼치기 */
.asset-body-wrap {{ display: flex; flex-direction: column; gap: 4px; }}
.asset-body {{ font-size: 11.5px; color: #606770; line-height: 1.6;
               white-space: pre-wrap; word-break: break-word;
               max-height: 72px; overflow: hidden;
               transition: max-height .3s ease; }}
.asset-body.expanded {{ max-height: 1000px; }}
.body-toggle-btn {{ background: none; border: none; color: #1877F2;
                    font-size: 11px; cursor: pointer; padding: 0;
                    text-align: left; font-weight: 600; }}
.body-toggle-btn:hover {{ text-decoration: underline; }}

.no-asset {{ font-size: 13px; color: #90949C; padding: 14px;
             background: #F7F8FA; border-radius: 8px; text-align: center;
             margin-top: 10px; }}

/* ── 기타 ── */
.error-box {{ background: #FFEBEE; border: 1px solid #FFCDD2; border-radius: 10px;
              padding: 16px 20px; color: #B71C1C; }}
.empty-state {{ text-align: center; padding: 60px 20px; color: #90949C; font-size: 15px; }}

/* ── 노션동기화 버튼 ── */
.sync-btn {{ background: #5B5FEF; color: white; border: none; padding: 7px 16px;
             border-radius: 20px; font-size: 13px; font-weight: 700; cursor: pointer; }}
.sync-btn:hover {{ background: #4449D0; }}
.sync-btn:disabled {{ background: #ccc; color: #888; cursor: not-allowed; }}

/* ── 동기화 모달 ── */
#syncOverlay {{ position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);
               z-index:1000;display:none;align-items:center;justify-content:center; }}
#syncOverlay.open {{ display:flex; }}
#syncBox {{ background:white;border-radius:16px;padding:28px 28px 24px;width:420px;
            max-width:92vw;box-shadow:0 8px 32px rgba(0,0,0,.22); }}
#syncBox h2 {{ font-size:16px;font-weight:700;margin:0 0 18px; }}
.sync-bar-wrap {{ background:#F0F2F5;border-radius:8px;height:10px;overflow:hidden;margin-bottom:10px; }}
.sync-bar {{ background:#5B5FEF;height:100%;width:0%;border-radius:8px;transition:width .4s; }}
#syncStatus {{ font-size:13px;color:#606770;margin-bottom:16px; }}
#syncLog {{ max-height:180px;overflow-y:auto;font-size:12px;display:flex;flex-direction:column;gap:5px; }}
.sync-log-item {{ padding:6px 10px;border-radius:8px;background:#F7F8FA; }}
.sync-log-item.ok {{ background:#E6F4EA;color:#137333; }}
.sync-log-item.fail {{ background:#FFEBEE;color:#B71C1C; }}
#syncCloseBtn {{ margin-top:18px;width:100%;padding:10px;background:#1877F2;color:white;
                 border:none;border-radius:8px;font-size:14px;font-weight:700;
                 cursor:pointer;display:none; }}
</style>
</head>
<body>
<div class="top-bar">
  <h1>⚙️ 메타광고세팅</h1>
  <div style="display:flex;gap:10px;align-items:center;">
    <button class="sync-btn" id="syncBtn" onclick="syncNotion()">🔄 노션동기화</button>
    <a href="/" class="back-btn">← 대시보드</a>
  </div>
</div>

<div id="syncOverlay">
  <div id="syncBox">
    <h2>🔄 노션 동기화</h2>
    <div class="sync-bar-wrap"><div class="sync-bar" id="syncBar"></div></div>
    <div id="syncStatus">준비 중...</div>
    <div id="syncLog"></div>
    <button id="syncCloseBtn" onclick="closeSyncModal()">닫기</button>
  </div>
</div>

<div class="wrap">
  <div class="summary-bar">
    <span class="total">총 {total}건</span>
    {summary}
    <span style="margin-left:auto;font-size:11px;color:#90949C;">Notion: 메타 광고 오토세팅 DB</span>
  </div>

  {body_html}
</div>

<script>
function onImgErr(img) {{
  const wrap = img.closest('.asset-img-wrap');
  if (wrap) wrap.innerHTML = '<div class="asset-img-empty"><span class="img-empty-icon">🖼</span><span>미리보기 불가</span></div>';
}}

function toggleBody(id, btn) {{
  const el = document.getElementById(id);
  if (!el) return;
  const expanded = el.classList.toggle('expanded');
  btn.textContent = expanded ? '접기 ▴' : '더보기 ▾';
}}

function syncNotion() {{
  const btn = document.getElementById('syncBtn');
  btn.disabled = true;
  document.getElementById('syncOverlay').classList.add('open');
  document.getElementById('syncBar').style.width = '0%';
  document.getElementById('syncStatus').textContent = '연결 중...';
  document.getElementById('syncLog').innerHTML = '';
  document.getElementById('syncCloseBtn').style.display = 'none';

  let _total = 1, _campIdx = 0, _subStep = 0, _subTotal = 9;
  const bar = document.getElementById('syncBar');
  const status = document.getElementById('syncStatus');

  function setBar(pct) {{
    bar.style.width = Math.min(pct, 99) + '%';
  }}

  const es = new EventSource('/notion-sync-sse');
  es.onmessage = function(e) {{
    const d = JSON.parse(e.data);
    if (d.type === 'status') {{
      status.textContent = d.msg;
      setBar(5);
    }} else if (d.type === 'total') {{
      _total = d.total;
      status.textContent = `총 ${{d.total}}개 캠페인 처리 예정`;
      setBar(8);
    }} else if (d.type === 'progress') {{
      _campIdx = d.current - 1;
      _subStep = 0;
      const base = (_campIdx / _total) * 90 + 8;
      setBar(base);
      status.textContent = `(${{d.current}}/${{d.total}}) ${{d.name}}`;
    }} else if (d.type === 'sub') {{
      _subStep++;
      const slotSize = 90 / _total;
      const base = (_campIdx / _total) * 90 + 8;
      const subPct = base + (_subStep / _subTotal) * slotSize;
      setBar(subPct);
      status.textContent = `(${{d.campaign_idx}}/${{d.total}}) ${{d.msg}}`;
    }} else if (d.type === 'item') {{
      const campDone = ((_campIdx + 1) / _total) * 90 + 8;
      setBar(campDone);
      const el = document.createElement('div');
      el.className = 'sync-log-item ' + (d.ok ? 'ok' : 'fail');
      el.textContent = (d.ok ? '✅ ' : '❌ ') + d.name + (d.error ? ' — ' + d.error : '');
      document.getElementById('syncLog').appendChild(el);
      _campIdx++;
      _subStep = 0;
    }} else if (d.type === 'done') {{
      setBar(100);
      bar.style.width = '100%';
      if (d.msg) {{
        status.textContent = d.msg;
      }} else {{
        const ok = (d.results || []).filter(r => r.ok).length;
        const fail = (d.results || []).filter(r => !r.ok).length;
        status.textContent = `완료 — 성공 ${{ok}}개${{fail ? ', 실패 ' + fail + '개' : ''}}`;
      }}
      document.getElementById('syncCloseBtn').style.display = 'block';
      btn.disabled = false;
      es.close();
    }} else if (d.type === 'error') {{
      status.textContent = '오류: ' + d.msg;
      bar.style.background = '#E53935';
      document.getElementById('syncCloseBtn').style.display = 'block';
      btn.disabled = false;
      es.close();
    }}
  }};
  es.onerror = function() {{
    status.textContent = '연결 오류가 발생했습니다.';
    document.getElementById('syncCloseBtn').style.display = 'block';
    btn.disabled = false;
    es.close();
  }};
}}

function closeSyncModal() {{
  document.getElementById('syncOverlay').classList.remove('open');
  location.reload();
}}

async function uploadCampaign(pageId, btn) {{
  if (!confirm('이 캠페인을 Meta에 업로드하시겠습니까?\\n\\n• Meta에 PAUSED 상태로 캠페인이 생성됩니다.\\n• 완료 후 노션 상태가 "업로드완료"로 변경됩니다.\\n• 이후 대시보드에서 ACTIVE 전환하세요.')) return;
  btn.disabled = true;
  btn.textContent = '업로드 중...';
  try {{
    const resp = await fetch('/ad-setup/run/' + pageId, {{ method: 'POST' }});
    const result = await resp.json();
    if (resp.ok) {{
      btn.textContent = '✅ 업로드 완료';
      btn.style.background = '#137333';
      const card = btn.closest('.camp-card');
      const chip = card.querySelector('.status-chip');
      if (chip) {{
        chip.textContent = '📤 업로드완료';
        chip.style.background = '#E3F2FD';
        chip.style.color = '#1565C0';
      }}
      card.style.borderTopColor = '#1565C0';
    }} else {{
      btn.textContent = '❌ 실패';
      btn.disabled = false;
      alert('업로드 실패:\\n' + (result.error || JSON.stringify(result)));
    }}
  }} catch(e) {{
    btn.textContent = '❌ 실패';
    btn.disabled = false;
    alert('오류: ' + e.message);
  }}
}}
</script>
</body>
</html>"""

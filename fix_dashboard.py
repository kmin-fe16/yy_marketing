import re

c = open('dashboard.html', encoding='utf-8').read()

# 1. 중복 .region-card CSS 제거 (margin-bottom 있는 구버전)
c = re.sub(
    r'\.region-card \{ background: white; border-radius: 12px; margin-bottom: 20px;[^\}]+\}',
    '', c, count=1
)

# 2. 미디어쿼리 밖에 있는 단독 .regions-grid { grid-template-columns: 1fr; } 제거
c = re.sub(r'\s*\.regions-grid \{ grid-template-columns: 1fr; \}\n', '\n', c)

# 3. 기존 모달 CSS 제거 후 깔끔하게 재삽입
c = re.sub(
    r'/\* 모달 \*/.*?\.modal-close:hover \{ color:#1C1E21; \}',
    '', c, flags=re.DOTALL
)
c = re.sub(
    r'\.modal-overlay \{.*?\}.*?\.modal-close:hover \{.*?\}',
    '', c, flags=re.DOTALL
)

modal_css = """
  /* 2열 그리드 */
  .regions-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
  @media (max-width: 900px) { .regions-grid { grid-template-columns: 1fr; } }

  /* 모달 */
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    z-index: 9999; align-items: center; justify-content: center; }
  .modal-overlay.open { display: flex !important; }
  .modal-box { background: white; border-radius: 16px; width: 90%; max-width: 920px;
    max-height: 85vh; overflow-y: auto; display: flex; flex-direction: column;
    box-shadow: 0 8px 40px rgba(0,0,0,0.25); }
  .modal-header { display: flex; align-items: center; justify-content: space-between;
    padding: 18px 24px; border-bottom: 1px solid #E4E6EB;
    position: sticky; top: 0; background: white; z-index: 1; }
  .modal-header h3 { font-size: 16px; font-weight: 700; }
  .modal-close { background: none; border: none; font-size: 24px; cursor: pointer;
    color: #606770; line-height: 1; padding: 0 4px; }
  .modal-close:hover { color: #1C1E21; }
  .modal-body { padding: 20px 24px; }
"""
c = c.replace('</style>', modal_css + '</style>', 1)

# 4. 기존 모달 HTML 제거 후 재삽입
c = re.sub(r'\n<!-- 모달 -->.*?</div>\n</div>\n', '\n', c, flags=re.DOTALL)

modal_html = """
<!-- 모달 -->
<div class="modal-overlay" id="regionModal">
  <div class="modal-box" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3 id="modalTitle">캠페인 상세</h3>
      <button class="modal-close" onclick="closeModal()">&#x2715;</button>
    </div>
    <div class="modal-body" id="modalBody"></div>
  </div>
</div>"""

c = re.sub(r'(\n</div>\n\n<script id="ads-data")', modal_html + r'\1', c, count=1)

# 5. 모달 JS 교체
new_js = """
// ── 모달 ─────────────────────────────────────────────────────────
function openModal(key) {
  var overlay = document.getElementById('regionModal');
  var body    = document.getElementById('modalBody');
  var titleEl = document.getElementById('modalTitle');
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
  body.innerHTML = '<p style="padding:20px;color:#999">불러오는 중...</p>';

  var card = document.querySelector('[data-region-key="' + key + '"]');
  var regionName = (card && card.querySelector('h2')) ? card.querySelector('h2').textContent.trim() : '';
  if (titleEl) titleEl.textContent = regionName + ' 캠페인 상세';

  var entries = [];
  Object.keys(ADS_DATA).forEach(function(cid) {
    var ads = ADS_DATA[cid];
    if (ads && ads.length && ads[0].name && ads[0].name.indexOf(regionName) !== -1) {
      entries.push({cid: cid, ads: ads});
    }
  });

  var creatives = '';
  entries.forEach(function(e) {
    var thumb = null;
    for (var i = 0; i < e.ads.length; i++) {
      if (e.ads[i].creative && e.ads[i].creative.thumbnail_url) { thumb = e.ads[i].creative.thumbnail_url; break; }
    }
    var name = e.ads[0] ? e.ads[0].name.replace(/-\d+$/, '') : '';
    var lm = name.match(/(\d+차|잠재)/);
    if (!lm) return;
    var img = thumb
      ? '<img class="creative-thumb" src="' + thumb + '" onerror="this.style.display=\'none\'">'
      : '<div class="creative-thumb-empty"></div>';
    creatives += '<div class="creative-item">' + img + '<span class="round-label">' + lm[0] + '</span></div>';
  });

  entries.sort(function(a, b) {
    function sp(e) { var d = e.ads[0] && e.ads[0].insights && e.ads[0].insights.data && e.ads[0].insights.data[0]; return d ? parseFloat(d.spend || 0) : 0; }
    return sp(b) - sp(a);
  });

  var rows = '';
  entries.forEach(function(e) {
    var d = e.ads[0] && e.ads[0].insights && e.ads[0].insights.data && e.ads[0].insights.data[0] ? e.ads[0].insights.data[0] : null;
    var ctr = d ? parseFloat(d.ctr || 0) : 0;
    var spend = d ? parseFloat(d.spend || 0) : 0;
    var imp = d ? parseInt(d.impressions || 0) : 0;
    var clk = d ? parseInt(d.clicks || 0) : 0;
    var st = e.ads[0] ? e.ads[0].status : '';
    var nm = e.ads[0] ? e.ads[0].name.replace(/-\d+$/, '') : e.cid;
    var bc = ctr >= 3 ? 'ctr-high' : ctr >= 1.5 ? 'ctr-mid' : 'ctr-low';
    var rc = st === 'ACTIVE' ? 'camp-active' : 'camp-paused';
    rows += '<tr class="camp-row ' + rc + '" onclick="toggleAds(this)" data-campaign-id="' + e.cid + '">' +
      '<td class="camp-name"><span class="expand-icon">&#9658;</span> ' + nm + '</td>' +
      '<td></td><td>' + (imp ? imp.toLocaleString() : '-') + '</td>' +
      '<td>' + (clk ? clk.toLocaleString() : '-') + '</td>' +
      '<td><span class="ctr-badge ' + bc + '">' + (d ? ctr.toFixed(2) + '%' : '-') + '</span></td>' +
      '<td>' + (spend ? '&#8361;' + Math.round(spend).toLocaleString() : '-') + '</td>' +
      '<td>-</td></tr>';
  });

  var html = '';
  if (creatives) html += '<div class="creative-strip">' + creatives + '</div>';
  html += '<div class="table-wrap" style="margin-top:8px"><table>' +
    '<thead><tr><th>캠페인명</th><th>시작일</th><th>노출수</th><th>클릭수</th><th>CTR</th><th>소진금액</th><th>도달수</th></tr></thead>' +
    '<tbody>' + (rows || '<tr><td colspan="7" style="text-align:center;padding:20px;color:#999">새로고침 후 확인 가능</td></tr>') + '</tbody></table></div>';
  body.innerHTML = html;
}
function closeModal() {
  document.getElementById('regionModal').classList.remove('open');
  document.body.style.overflow = '';
}
document.getElementById('regionModal').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeModal(); });

"""

start = c.find('function openModal')
end   = c.find("document.addEventListener('keydown'", start)
if end == -1:
    end = c.find('document.addEventListener("keydown"', start)
end = c.find(';', end) + 1
if start != -1 and end > start:
    c = c[:start] + new_js + c[end:]
    print('JS 교체 완료')
else:
    idx = c.find('const ADS_DATA')
    c = c[:idx] + new_js + c[idx:]
    print('JS ADS_DATA 앞에 삽입')

open('dashboard.html', 'w', encoding='utf-8').write(c)

print('regions-grid CSS 수:', c.count('.regions-grid {'))
print('modal-overlay.open:', '.modal-overlay.open' in c)
print('modal HTML:', 'id="regionModal"' in c)
print('openModal 개수:', c.count('function openModal'))
print('spendChart:', 'spendChart' in c)
print('region-card 개수:', c.count('<div class="region-card"'))

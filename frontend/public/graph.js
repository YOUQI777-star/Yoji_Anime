/* ═══════════════════════════════════════════════════════
   YOJI — Graph page logic
   Cytoscape · Search · Expand · Panels · Favorites · AI
═══════════════════════════════════════════════════════ */

/* ── Node / edge colours (mirrors style.css :root) ── */
const C = {
  bg:      '#0b0a09',
  surface: '#131210',
  s2:      '#1c1b18',
  border:  'rgba(255,255,255,0.06)',
  border2: 'rgba(255,255,255,0.13)',
  text:    '#ece9e1',
  muted:   '#5a5854',
  red:     '#c01818',
  anime:   '#ece9e1',
  char:    '#22c55e',
  va:      '#e8a020',
  tag:     '#4b5563',
  studio:  '#8b5cf6',
  country: '#0ea5e9',
};

const TYPE_COLOR = {
  Anime:      C.anime,
  Character:  C.char,
  VoiceActor: C.va,
  Tag:        C.tag,
  Studio:     C.studio,
  Country:    C.country,
};

const EDGE_COLOR = {
  HAS_CHARACTER: 'rgba(34,197,94,0.45)',
  VOICED_BY:     'rgba(232,160,32,0.45)',
  HAS_TAG:       'rgba(255,255,255,0.10)',
  RELATED_TO:    '#c01818',
  PRODUCED_BY:   'rgba(139,92,246,0.45)',
  ORIGIN_COUNTRY:'rgba(14,165,233,0.30)',
};

/* ── State ─────────────────────────────────────────── */
let cy = null;
let acTimer = null;
let acIndex = -1;
let currentLang = 'cn';
let currentScope = 'all';
let selectedNodeId = null;
let favMap = {};      // favorite_id → { item_type, item_raw_id }
let favKeySet = new Set(); // "Type:raw_id"
let selectedTags = [];
let askAbort = null;

/* ── Cytoscape init ────────────────────────────────── */
function initCy() {
  cy = cytoscape({
    container: document.getElementById('cy'),
    style: getCyStyle(),
    elements: [],
    layout: { name: 'preset' },
    minZoom: 0.1,
    maxZoom: 3,
    wheelSensitivity: 0.3,
  });

  cy.on('tap', 'node', e => onNodeTap(e.target));
  cy.on('tap', e => { if (e.target === cy) closeRightPanel(); });
}

function getCyStyle() {
  return [
    {
      selector: 'node',
      style: {
        'background-color': C.s2,
        'border-color': C.border2,
        'border-width': 1,
        'label': 'data(label)',
        'color': C.text,
        'font-family': '"Space Mono", monospace',
        'font-size': 9,
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 5,
        'text-background-color': C.bg,
        'text-background-opacity': 0.75,
        'text-background-padding': 2,
        'width': 22,
        'height': 22,
        'transition-property': 'border-color, border-width',
        'transition-duration': '0.15s',
      }
    },
    {
      selector: 'node[type="Anime"]',
      style: {
        'background-color': C.anime,
        'border-color': C.anime,
        'color': C.text,
        'width': 30, 'height': 30,
        'font-size': 10,
        'font-weight': 700,
      }
    },
    {
      selector: 'node[type="Character"]',
      style: {
        'background-color': C.char,
        'border-color': C.char,
        'width': 20, 'height': 20,
      }
    },
    {
      selector: 'node[type="VoiceActor"]',
      style: {
        'background-color': C.va,
        'border-color': C.va,
        'width': 22, 'height': 22,
      }
    },
    {
      selector: 'node[type="Tag"]',
      style: {
        'background-color': C.tag,
        'border-color': C.tag,
        'shape': 'diamond',
        'width': 16, 'height': 16,
      }
    },
    {
      selector: 'node[type="Studio"]',
      style: {
        'background-color': C.studio,
        'border-color': C.studio,
        'shape': 'hexagon',
        'width': 22, 'height': 22,
      }
    },
    {
      selector: 'node[type="Country"]',
      style: {
        'background-color': C.country,
        'border-color': C.country,
        'shape': 'pentagon',
        'width': 16, 'height': 16,
      }
    },
    {
      selector: 'node:selected',
      style: {
        'border-color': C.red,
        'border-width': 3,
      }
    },
    {
      selector: 'edge',
      style: {
        'line-color': C.border2,
        'width': 1,
        'curve-style': 'bezier',
        'target-arrow-shape': 'none',
        'label': '',
        'opacity': 0.7,
      }
    },
    ...Object.entries(EDGE_COLOR).map(([type, color]) => ({
      selector: `edge[label="${type}"]`,
      style: { 'line-color': color, 'width': type === 'RELATED_TO' ? 1.5 : 1 }
    })),
    {
      selector: 'edge[label="RELATED_TO"]',
      style: {
        'target-arrow-shape': 'triangle',
        'target-arrow-color': C.red,
        'arrow-scale': 0.8,
      }
    },
    {
      selector: '.faded',
      style: { 'opacity': 0.15 }
    },
  ];
}

/* ── Graph data loading ────────────────────────────── */
function loadGraph(data, replace = true) {
  if (!cy) return;
  if (replace) cy.elements().remove();

  const existingIds = new Set(cy.nodes().map(n => n.id()));
  const newEls = [];

  for (const n of (data.nodes || [])) {
    if (!existingIds.has(n.data.id)) {
      newEls.push({ group: 'nodes', data: n.data });
    }
  }
  for (const e of (data.edges || [])) {
    if (!cy.getElementById(e.data.id).length) {
      newEls.push({ group: 'edges', data: e.data });
    }
  }

  if (newEls.length) cy.add(newEls);

  runLayout(replace);
  updateGraphStats();
}

function runLayout(full = false) {
  const nodeCount = cy.nodes().length;
  if (nodeCount === 0) return;

  const layout = cy.layout({
    name: 'cose',
    animate: nodeCount < 80,
    animationDuration: 400,
    randomize: full,
    nodeRepulsion: () => 6000,
    idealEdgeLength: () => 80,
    edgeElasticity: () => 100,
    gravity: 0.3,
    numIter: 800,
    fit: true,
    padding: 40,
  });
  layout.run();
}

function updateGraphStats() {
  const el = document.getElementById('graph-stats');
  if (el) {
    el.textContent = `${cy.nodes().length}N · ${cy.edges().length}E`;
  }
}

function showGraphLoading(show) {
  const el = document.getElementById('graph-loading');
  if (el) el.classList.toggle('show', show);
}

/* ── Search & Autocomplete ─────────────────────────── */
function initSearch() {
  const input = document.getElementById('nav-search');
  const acList = document.getElementById('ac-list');
  if (!input || !acList) return;

  input.addEventListener('input', () => {
    clearTimeout(acTimer);
    const q = input.value.trim();
    if (q.length < 1) { hideAc(); return; }
    acTimer = setTimeout(() => fetchAc(q), 220);
  });

  input.addEventListener('keydown', e => {
    const items = acList.querySelectorAll('.ac-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      acIndex = Math.min(acIndex + 1, items.length - 1);
      highlightAc(items);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      acIndex = Math.max(acIndex - 1, -1);
      highlightAc(items);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (acIndex >= 0 && items[acIndex]) {
        items[acIndex].click();
      } else {
        doSearch(input.value.trim());
        hideAc();
      }
    } else if (e.key === 'Escape') {
      hideAc();
    }
  });

  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !acList.contains(e.target)) hideAc();
  });
}

async function fetchAc(q) {
  try {
    const items = await apiFetch(`/autocomplete?q=${encodeURIComponent(q)}`);
    renderAc(items);
  } catch {}
}

function renderAc(items) {
  const list = document.getElementById('ac-list');
  if (!items.length) { hideAc(); return; }
  list.innerHTML = items.map((it, i) => `
    <div class="ac-item" data-id="${it.id}" data-idx="${i}"
         onclick="acSelect(${it.id}, '${escHtml(it.name_cn || it.name)}')">
      <span class="ac-name">${escHtml(it.name_cn || it.name)}</span>
      ${it.name_cn && it.name ? `<span class="ac-sub">${escHtml(it.name)}</span>` : ''}
    </div>
  `).join('');
  acIndex = -1;
  list.style.display = 'block';
}

function highlightAc(items) {
  items.forEach((el, i) => el.classList.toggle('focused', i === acIndex));
}

function hideAc() {
  const list = document.getElementById('ac-list');
  if (list) { list.style.display = 'none'; list.innerHTML = ''; }
  acIndex = -1;
}

function acSelect(animeId, name) {
  document.getElementById('nav-search').value = name;
  hideAc();
  doSearchById(animeId);
}

async function doSearch(query) {
  if (!query) return;
  showGraphLoading(true);
  try {
    const data = await apiFetch(
      `/search?query=${encodeURIComponent(query)}&scope=${currentScope}&display_lang=${currentLang}&limit=50`
    );
    loadGraph(data, true);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

async function doSearchById(animeId) {
  showGraphLoading(true);
  try {
    const data = await apiFetch(`/expand?id=${animeId}&type=Anime&display_lang=${currentLang}&limit=40`);
    loadGraph(data, true);
    // Also show detail for this anime
    const node = cy.nodes(`[raw_id="${animeId}"][type="Anime"]`).first();
    if (node.length) {
      node.select();
      openDetailForNode(node.data());
    }
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

/* ── Left panel tabs ───────────────────────────────── */
function initLeftPanel() {
  // Tab switching
  document.querySelectorAll('.ptab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.ptab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.ptab-pane').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const pane = document.getElementById('pane-' + tab.dataset.pane);
      if (pane) pane.classList.add('active');
    });
  });

  // Scope buttons
  document.querySelectorAll('.scope-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.scope-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentScope = btn.dataset.scope;
    });
  });

  // Lang buttons
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentLang = btn.dataset.lang;
    });
  });

  // Niche sliders
  const popSlider  = document.getElementById('niche-pop');
  const richSlider = document.getElementById('niche-rich');
  if (popSlider)  popSlider.addEventListener('input',  () => document.getElementById('niche-pop-val').textContent  = popSlider.value);
  if (richSlider) richSlider.addEventListener('input', () => document.getElementById('niche-rich-val').textContent = richSlider.value);

  // Load popular tags for casting pane
  loadPopularTags();
}

async function loadPopularTags() {
  const pool = document.getElementById('tag-pool');
  if (!pool) return;
  try {
    const data = await apiFetch('/tags?limit=40');
    pool.innerHTML = data.tags.slice(0, 40).map(t =>
      `<span class="tag-chip" onclick="toggleTag(this, '${escHtml(t.name)}')">${escHtml(t.name)}</span>`
    ).join('');
  } catch {}
}

function toggleTag(el, name) {
  const idx = selectedTags.indexOf(name);
  if (idx >= 0) {
    selectedTags.splice(idx, 1);
    el.classList.remove('sel');
  } else {
    selectedTags.push(name);
    el.classList.add('sel');
  }
  const countEl = document.getElementById('sel-tag-count');
  if (countEl) countEl.textContent = selectedTags.length ? `${selectedTags.length} selected` : '';
}

/* ── Panel actions (called from HTML) ──────────────── */
async function runSearchPane() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) { toast('ENTER A QUERY', 'err'); return; }
  document.getElementById('nav-search').value = q;
  await doSearch(q);
}

async function runRecommend() {
  const input = document.getElementById('rec-input').value.trim();
  if (!input) { toast('ENTER ANIME NAME OR ID', 'err'); return; }
  showGraphLoading(true);
  try {
    const param = /^\d+$/.test(input) ? `id=${input}` : `name=${encodeURIComponent(input)}`;
    const data = await apiFetch(`/recommend?${param}&display_lang=${currentLang}&limit=10`);
    loadGraph({ nodes: data.nodes, edges: data.edges }, true);
    renderRecList(data.recommendations);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

function renderRecList(recs) {
  const el = document.getElementById('rec-results');
  if (!el) return;
  if (!recs || !recs.length) { el.innerHTML = '<div class="empty-state">NO RESULTS</div>'; return; }
  el.innerHTML = recs.map(r => `
    <div class="rec-item" onclick="doSearchById(${r.id})">
      <div class="rec-name">${escHtml(r.name_cn || r.name)}</div>
      <div class="rec-expl">
        TAGS:${r.explanation.shared_tags} · VA:${r.explanation.shared_voice_actors} · STU:${r.explanation.shared_studios}
      </div>
    </div>
  `).join('');
}

async function runCasting() {
  if (!selectedTags.length) { toast('SELECT AT LEAST ONE TAG', 'err'); return; }
  showGraphLoading(true);
  try {
    const data = await apiFetch(`/casting?tags=${encodeURIComponent(selectedTags.join(','))}&display_lang=${currentLang}&limit=15`);
    loadGraph({ nodes: data.nodes, edges: data.edges }, true);
    // Show VA summary
    if (data.voice_actor_summary && data.voice_actor_summary.length) {
      const el = document.getElementById('cast-results');
      if (el) {
        el.innerHTML = data.voice_actor_summary.slice(0, 8).map(v =>
          `<div class="rec-item" onclick="expandVA('${escHtml(v.name)}')">
            <div class="rec-name">${escHtml(v.name)}</div>
            <div class="rec-expl">ANIME:${v.matched_anime_count} · SCORE:${v.summary_score.toFixed(1)}</div>
          </div>`
        ).join('');
      }
    }
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

async function expandVA(name) {
  showGraphLoading(true);
  try {
    const data = await apiFetch(`/expand?id=${encodeURIComponent(name)}&type=VoiceActor&display_lang=${currentLang}&limit=30`);
    loadGraph(data, false);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

async function runNiche() {
  const pop  = document.getElementById('niche-pop').value;
  const rich = document.getElementById('niche-rich').value;
  showGraphLoading(true);
  try {
    const data = await apiFetch(`/niche?pop=${pop}&rich=${rich}&display_lang=${currentLang}&limit=40`);
    loadGraph(data, true);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

/* ── Node click → right panel ─────────────────────── */
function onNodeTap(node) {
  cy.nodes().unselect();
  node.select();
  selectedNodeId = node.id();
  openDetailForNode(node.data());
}

function openDetailForNode(data) {
  // Header
  document.querySelector('.rp-badge').className = `rp-badge badge-${data.type}`;
  document.querySelector('.rp-badge').textContent = data.type.toUpperCase();
  document.querySelector('.rp-name').textContent  = data.label;

  // Clear content
  const scroll = document.getElementById('rp-scroll');
  scroll.innerHTML = '';

  // Render by type
  if (data.type === 'Anime') renderAnimePanel(data);
  else renderGenericPanel(data);

  openRightPanel();
}

function openRightPanel() {
  document.getElementById('rp').classList.add('open');
}

function closeRightPanel() {
  document.getElementById('rp').classList.remove('open');
  cy.nodes().unselect();
  selectedNodeId = null;
}

/* ── Anime detail panel ────────────────────────────── */
async function renderAnimePanel(data) {
  const scroll = document.getElementById('rp-scroll');
  const animeId = data.raw_id;
  const favKey  = `Anime:${animeId}`;
  const isFaved = favKeySet.has(favKey);

  // Cover placeholder + actions
  scroll.innerHTML = `
    <div id="rp-cover-wrap">
      <div class="rp-cover-ph"><span class="spin"></span></div>
    </div>
    <div class="rp-actions">
      <button class="btn btn-ghost btn-sm" onclick="expandCurrentNode()">EXPAND</button>
      <button id="fav-btn" class="btn btn-sm ${isFaved ? 'btn-danger' : 'btn-ghost'}"
              onclick="toggleFavorite(${JSON.stringify(data).replace(/"/g,"'")})">
        ${isFaved ? '★ SAVED' : '☆ SAVE'}
      </button>
    </div>
    <div id="rp-info"></div>
    <div id="rp-ask-wrap"></div>
  `;

  // Load cover
  try {
    const cov = await apiFetch(`/cover?id=${animeId}`);
    const wrap = document.getElementById('rp-cover-wrap');
    if (wrap) {
      if (cov.image_url) {
        wrap.innerHTML = `<img class="rp-cover" src="${cov.image_url}" alt="cover" loading="lazy" />`;
      } else {
        wrap.innerHTML = `<div class="rp-cover-ph" style="font-size:10px;font-family:var(--mono);color:var(--muted)">NO COVER</div>`;
      }
    }
  } catch {}

  // Load anime detail
  try {
    const detail = await apiFetch(`/anime?id=${animeId}`);
    const infoEl = document.getElementById('rp-info');
    if (!infoEl) return;

    const rows = [];
    if (detail.score || detail.rank) {
      rows.push(`
        <div style="padding:6px 0;border-bottom:1px solid var(--border)">
          <div class="score-block">
            <span class="score-num">${detail.score ?? '—'}</span>
            <span class="score-rank"># ${detail.rank ?? '—'}</span>
          </div>
        </div>
      `);
    }
    if (detail.date)     rows.push(infoRow('DATE', detail.date));
    if (detail.platform) rows.push(infoRow('PLATFORM', detail.platform));
    if (detail.episodes) rows.push(infoRow('EPS', detail.episodes));
    if (detail.director) rows.push(infoRow('DIRECTOR', detail.director));
    if (detail.studios?.filter(Boolean).length)
      rows.push(infoRow('STUDIO', detail.studios.filter(Boolean).join(', ')));
    if (detail.countries?.filter(Boolean).length)
      rows.push(infoRow('COUNTRY', detail.countries.filter(Boolean).join(', ')));

    const tags = (detail.tags || []).filter(Boolean);
    const tagHtml = tags.length
      ? `<div class="tags-inline">${tags.map(t =>
          `<span class="tag-pill" onclick="expandTag('${escHtml(t)}')" title="Expand tag" style="cursor:pointer">${escHtml(t)}</span>`
        ).join('')}</div>`
      : '';

    let summaryHtml = '';
    if (detail.summary) {
      const full = escHtml(detail.summary);
      summaryHtml = `
        <div>
          <div class="pane-label" style="margin-bottom:6px">SUMMARY</div>
          <div class="summary-text" id="summary-txt">${full}</div>
          ${detail.summary.length > 200 ? `<span class="summary-more" onclick="toggleSummary()">[ MORE ]</span>` : ''}
        </div>
      `;
    }

    infoEl.innerHTML = `
      <div class="info-rows">${rows.join('')}</div>
      ${tags.length ? `<div><div class="pane-label" style="margin-bottom:6px">TAGS</div>${tagHtml}</div>` : ''}
      ${summaryHtml}
    `;
  } catch {}

  // AI Ask widget
  const askWrap = document.getElementById('rp-ask-wrap');
  if (askWrap) {
    askWrap.innerHTML = `
      <div class="pane-label">AI QUERY</div>
      <div class="ask-wrap">
        <textarea class="ask-ta" id="ask-input" placeholder="Ask about this anime…" rows="2"></textarea>
        <div class="ask-foot">
          <span class="ask-src" id="ask-src"></span>
          <button class="btn btn-primary btn-sm" onclick="submitAsk(${animeId})">ASK →</button>
        </div>
        <div class="ask-resp" id="ask-resp"></div>
      </div>
    `;
    document.getElementById('ask-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitAsk(animeId); }
    });
  }
}

function infoRow(key, val) {
  return `<div class="info-row"><span class="info-key">${key}</span><span class="info-val">${escHtml(String(val))}</span></div>`;
}

function toggleSummary() {
  const el = document.getElementById('summary-txt');
  const btn = document.querySelector('.summary-more');
  if (!el) return;
  el.classList.toggle('expanded');
  if (btn) btn.textContent = el.classList.contains('expanded') ? '[ LESS ]' : '[ MORE ]';
}

/* ── Generic node panel ────────────────────────────── */
function renderGenericPanel(data) {
  const scroll = document.getElementById('rp-scroll');
  const favKey = `${data.type}:${data.raw_id}`;
  const canFav = ['Character', 'VoiceActor'].includes(data.type);
  const isFaved = favKeySet.has(favKey);

  let extraBtn = '';
  if (canFav) {
    extraBtn = `<button id="fav-btn" class="btn btn-sm ${isFaved ? 'btn-danger' : 'btn-ghost'}"
      onclick="toggleFavorite(${JSON.stringify(data).replace(/"/g,"'")})">
      ${isFaved ? '★ SAVED' : '☆ SAVE'}
    </button>`;
  }

  scroll.innerHTML = `
    <div class="info-rows">
      ${infoRow('TYPE', data.type)}
      ${infoRow('ID', data.raw_id)}
    </div>
    <div class="rp-actions">
      <button class="btn btn-ghost btn-sm" onclick="expandCurrentNode()">EXPAND</button>
      ${extraBtn}
    </div>
  `;
}

/* ── Expand node ───────────────────────────────────── */
function expandCurrentNode() {
  if (!selectedNodeId) return;
  const node = cy.getElementById(selectedNodeId);
  if (!node.length) return;
  const data = node.data();
  doExpand(data.raw_id, data.type);
}

async function doExpand(rawId, type) {
  showGraphLoading(true);
  try {
    const data = await apiFetch(
      `/expand?id=${encodeURIComponent(rawId)}&type=${type}&display_lang=${currentLang}&limit=35`
    );
    loadGraph(data, false);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

async function expandTag(tagName) {
  showGraphLoading(true);
  try {
    const data = await apiFetch(`/expand?id=${encodeURIComponent(tagName)}&type=Tag&display_lang=${currentLang}&limit=25`);
    loadGraph(data, false);
  } catch (err) {
    toast(err.message, 'err');
  } finally {
    showGraphLoading(false);
  }
}

/* ── Favorites ─────────────────────────────────────── */
async function loadFavorites() {
  if (!isLoggedIn()) return;
  try {
    const data = await apiFetch('/favorites');
    favMap = {};
    favKeySet = new Set();
    for (const type of ['Anime', 'Character', 'VoiceActor']) {
      for (const f of (data.favorites[type] || [])) {
        const key = `${f.item_type}:${f.item_raw_id}`;
        favMap[f.favorite_id] = { item_type: f.item_type, item_raw_id: f.item_raw_id };
        favKeySet.add(key);
      }
    }
  } catch {}
}

async function toggleFavorite(dataObj) {
  if (!isLoggedIn()) {
    showAuthModal('login');
    return;
  }
  const type  = typeof dataObj === 'string' ? JSON.parse(dataObj.replace(/'/g,'"')).type  : dataObj.type;
  const rawId = typeof dataObj === 'string' ? JSON.parse(dataObj.replace(/'/g,'"')).raw_id : dataObj.raw_id;
  const label = typeof dataObj === 'string' ? JSON.parse(dataObj.replace(/'/g,'"')).label  : dataObj.label;
  const key   = `${type}:${rawId}`;

  if (favKeySet.has(key)) {
    // find favorite_id
    const favId = Object.keys(favMap).find(id =>
      favMap[id].item_type === type && favMap[id].item_raw_id === String(rawId)
    );
    if (!favId) return;
    try {
      await apiFetch(`/favorites/${favId}`, { method: 'DELETE' });
      delete favMap[favId];
      favKeySet.delete(key);
      toast('REMOVED FROM FAVORITES');
      updateFavBtn(false);
    } catch (err) {
      toast(err.message, 'err');
    }
  } else {
    try {
      const res = await apiFetch('/favorites', {
        method: 'POST',
        body: JSON.stringify({ item_type: type, item_raw_id: String(rawId), item_display_name: label })
      });
      favMap[res.favorite_id] = { item_type: type, item_raw_id: String(rawId) };
      favKeySet.add(key);
      toast('SAVED TO FAVORITES', 'ok');
      updateFavBtn(true);
    } catch (err) {
      toast(err.message, 'err');
    }
  }
}

function updateFavBtn(isFaved) {
  const btn = document.getElementById('fav-btn');
  if (!btn) return;
  btn.className = `btn btn-sm ${isFaved ? 'btn-danger' : 'btn-ghost'}`;
  btn.textContent = isFaved ? '★ SAVED' : '☆ SAVE';
}

/* ── AI Ask (SSE) ──────────────────────────────────── */
async function submitAsk(animeId) {
  const input = document.getElementById('ask-input');
  const resp  = document.getElementById('ask-resp');
  const srcEl = document.getElementById('ask-src');
  if (!input || !resp) return;

  const question = input.value.trim();
  if (!question) return;

  if (askAbort) { askAbort.abort(); }
  askAbort = new AbortController();

  resp.textContent = '';
  resp.classList.add('show');
  if (srcEl) srcEl.textContent = '...';

  try {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`${API_BASE}/ask`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ question, anime_id: animeId }),
      signal: askAbort.signal,
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      resp.textContent = body.error || 'AI unavailable';
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        try {
          const obj = JSON.parse(raw);
          if (obj.done) {
            if (srcEl) srcEl.textContent = obj.source === 'knowledge_graph' ? 'KG+AI' : 'AI';
            break;
          }
          if (obj.delta) resp.textContent += obj.delta;
        } catch {}
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      resp.textContent = 'Error: ' + err.message;
    }
  }
}

/* ── Graph toolbar ─────────────────────────────────── */
function fitGraph()    { if (cy) cy.fit(undefined, 40); }
function clearGraph()  { if (cy) { cy.elements().remove(); updateGraphStats(); closeRightPanel(); } }
function toggleLP()    {
  const lp = document.getElementById('lp');
  lp.classList.toggle('collapsed');
}

/* ── Utility ───────────────────────────────────────── */
function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}

/* ── Init ──────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  initShared();
  initCy();
  initSearch();
  initLeftPanel();
  await loadFavorites();

  // If URL has ?q= pre-fill search
  const params = new URLSearchParams(window.location.search);
  const q = params.get('q');
  if (q) {
    document.getElementById('nav-search').value = q;
    doSearch(q);
  }
});

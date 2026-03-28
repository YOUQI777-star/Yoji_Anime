/* ═══════════════════════════════════════════════════════
   YOJI — Graph page logic
   Cytoscape · Search · Expand · Panels · Favorites · AI
═══════════════════════════════════════════════════════ */

/* ── Node / edge colours (mirrors style.css :root) ── */
const C = {
  bg: "#111317",
  surface: "#1b1c20",
  s2: "#23242a",
  border: "rgba(255,255,255,0.06)",
  border2: "rgba(255,255,255,0.12)",
  text: "#f3ebdd",
  muted: "#8e857f",
  red: "#c9775e",

  anime: "#f3ebdd",
  char: "#d58a73",
  va: "#e7b07a",
  tag: "#8fa7c6",
  studio: "#c59ab2",
  country: "#7d92b8"
};

const TYPE_COLOR = {
  Anime: C.anime,
  Character: C.char,
  VoiceActor: C.va,
  Tag: C.tag,
  Studio: C.studio,
  Country: C.country
};

const EDGE_COLOR = {
  HAS_CHARACTER: "rgba(213,138,115,0.40)",
  VOICED_BY: "rgba(231,176,122,0.42)",
  HAS_TAG: "rgba(143,167,198,0.28)",
  RELATED_TO: "#c9775e",
  PRODUCED_BY: "rgba(197,154,178,0.38)",
  ORIGIN_COUNTRY: "rgba(125,146,184,0.34)"
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
let expandLimit    = 20;   // controlled by toolbar select
let showEdgeLabels = false; // edge label toggle
let _tapTimer      = null;  // single/double-click de-conflict
let _focusNodeId   = null;  // current depth-style focus node

const GRAPH_RUNTIME_I18N = {
  en: {
    selected: 'selected',
    enterQuery: 'ENTER A QUERY',
    enterAnimeNameOrId: 'ENTER ANIME NAME OR ID',
    noResults: 'NO RESULTS',
    tagsShort: 'TAGS',
    vaShort: 'VA',
    studioShort: 'STU',
    selectAtLeastOneTag: 'SELECT AT LEAST ONE TAG',
    animeShort: 'ANIME',
    scoreShort: 'SCORE',
    expand: 'EXPAND',
    save: '☆ SAVE',
    saved: '★ SAVED',
    noCover: 'NO COVER',
    date: 'DATE',
    platform: 'PLATFORM',
    eps: 'EPS',
    director: 'DIRECTOR',
    studio: 'STUDIO',
    country: 'COUNTRY',
    tags: 'TAGS',
    summary: 'SUMMARY',
    more: '[ MORE ]',
    less: '[ LESS ]',
    aiQuery: 'AI QUERY',
    askPlaceholder: 'Ask about this anime…',
    askBtn: 'ASK →',
    type: 'TYPE',
    id: 'ID',
    removedFromFavorites: 'REMOVED FROM FAVORITES',
    savedToFavorites: 'SAVED TO FAVORITES',
    aiUnavailable: 'AI unavailable',
    errorPrefix: 'Error: '
  },
  zh: {
    selected: '已选',
    enterQuery: '请输入查询内容',
    enterAnimeNameOrId: '请输入动漫名称或 ID',
    noResults: '暂无结果',
    tagsShort: '标签',
    vaShort: '声优',
    studioShort: '制作',
    selectAtLeastOneTag: '请至少选择一个标签',
    animeShort: '动漫',
    scoreShort: '评分',
    expand: '展开',
    save: '☆ 收藏',
    saved: '★ 已收藏',
    noCover: '暂无封面',
    date: '日期',
    platform: '平台',
    eps: '集数',
    director: '导演',
    studio: '制作',
    country: '国家',
    tags: '标签',
    summary: '简介',
    more: '[ 展开 ]',
    less: '[ 收起 ]',
    aiQuery: 'AI 提问',
    askPlaceholder: '问问这部作品……',
    askBtn: '提问 →',
    type: '类型',
    id: 'ID',
    removedFromFavorites: '已从收藏中移除',
    savedToFavorites: '已加入收藏',
    aiUnavailable: 'AI 当前不可用',
    errorPrefix: '错误：'
  }
};

function graphUiLang() {
  return localStorage.getItem('yoji_lang') === 'zh' ? 'zh' : 'en';
}

function gt(key) {
  const lang = graphUiLang();
  return (GRAPH_RUNTIME_I18N[lang] && GRAPH_RUNTIME_I18N[lang][key]) || GRAPH_RUNTIME_I18N.en[key] || key;
}

/* ── Cytoscape init ────────────────────────────────── */
function initCy() {
  cy = cytoscape({
    container: document.getElementById('cy'),
    style: getCyStyle(),
    elements: [],
    layout: { name: 'preset' },
    minZoom: 0.3,
    maxZoom: 3,
    wheelSensitivity: 0.3,
  });

  // ── single/double-click de-conflict ──────────────────
  cy.on('tap', 'node', e => {
    const node = e.target;
    if (_tapTimer) { clearTimeout(_tapTimer); _tapTimer = null; return; }
    _tapTimer = setTimeout(() => { _tapTimer = null; onNodeTap(node); }, 250);
  });
  cy.on('dbltap', 'node', e => {
    clearTimeout(_tapTimer); _tapTimer = null;
    onNodeDblTap(e.target);
  });
  cy.on('tap', e => { if (e.target === cy) closeRightPanel(); });

  // ── keep canvas size in sync on resize (no auto-fit) ─
  let _resizeT;
  window.addEventListener('resize', () => {
    clearTimeout(_resizeT);
    _resizeT = setTimeout(() => { if (cy) cy.resize(); }, 200);
  });
}

function getCyStyle() {
  return [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        "border-width": 1.5,
        "border-color": "data(color)",
        "label": "data(label)",
        "color": C.text,
        "font-family": '"Be Vietnam Pro", system-ui, sans-serif',
        "font-size": 10,
        "font-weight": 600,
        "text-wrap": "wrap",
        "text-max-width": 92,
        "text-valign": "bottom",
        "text-margin-y": 8,
        "text-background-color": "rgba(10,12,18,0.82)",
        "text-background-opacity": 1,
        "text-background-padding": 3,
        "text-background-shape": "roundrectangle",
        "width": 22,
        "height": 22
      }
    },

    {
      selector: 'node[type="Anime"]',
      style: {
        "background-color": C.anime,
        "border-color": C.anime,
        "color": C.text,
        "width": 32,
        "height": 32,
        "font-size": 10,
        "font-weight": 700
      }
    },

    {
      selector: 'node[type="Character"]',
      style: {
        "background-color": C.char,
        "border-color": C.char,
        "width": 22,
        "height": 22
      }
    },

    {
      selector: 'node[type="VoiceActor"]',
      style: {
        "background-color": C.va,
        "border-color": C.va,
        "width": 22,
        "height": 22
      }
    },

    {
      selector: 'node[type="Tag"]',
      style: {
        "background-color": C.tag,
        "border-color": C.tag,
        "shape": "roundrectangle",
        "width": 18,
        "height": 18
      }
    },

    {
      selector: 'node[type="Studio"]',
      style: {
        "background-color": C.studio,
        "border-color": C.studio,
        "shape": "roundrectangle",
        "width": 20,
        "height": 20
      }
    },

    {
      selector: 'node[type="Country"]',
      style: {
        "background-color": C.country,
        "border-color": C.country,
        "shape": "ellipse",
        "width": 18,
        "height": 18
      }
    },

    {
      selector: "node:selected",
      style: {
        "border-color": C.red,
        "border-width": 3,
        "overlay-color": C.red,
        "overlay-opacity": 0.08
      }
    },

    {
      selector: "edge",
      style: {
        "line-color": C.border2,
        "width": 1.15,
        "curve-style": "bezier",
        "target-arrow-shape": "none",
        "label": "",
        "opacity": 0.58
      }
    },

    {
      selector: 'edge[type="HAS_CHARACTER"]',
      style: {
        "line-color": EDGE_COLOR.HAS_CHARACTER
      }
    },

    {
      selector: 'edge[type="VOICED_BY"]',
      style: {
        "line-color": EDGE_COLOR.VOICED_BY
      }
    },

    {
      selector: 'edge[type="HAS_TAG"]',
      style: {
        "line-color": EDGE_COLOR.HAS_TAG
      }
    },

    {
      selector: 'edge[type="PRODUCED_BY"]',
      style: {
        "line-color": EDGE_COLOR.PRODUCED_BY
      }
    },

    {
      selector: 'edge[type="ORIGIN_COUNTRY"]',
      style: {
        "line-color": EDGE_COLOR.ORIGIN_COUNTRY
      }
    },

    {
      selector: 'edge[type="RELATED_TO"]',
      style: {
        "line-color": EDGE_COLOR.RELATED_TO,
        "target-arrow-shape": "triangle",
        "target-arrow-color": C.red,
        "arrow-scale": 0.72,
        "opacity": 0.82
      }
    }
  ];
}

/* ── Graph data loading ────────────────────────────── */
function loadGraph(data, replace = true, fitView = true) {
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

  // auto-apply edge labels if REL mode is on
  if (showEdgeLabels) {
    cy.edges().style('label', e => e.data('type') || '');
    cy.edges().style('font-size', 8);
  }

  runLayout(replace, fitView);
  updateGraphStats();
}

function runLayout(full = false, fitView = true) {
  const nodeCount = cy.nodes().length;
  if (nodeCount === 0) return;

  cy.resize(); // sync canvas size before layout
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
    fit: fitView,
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
  if (countEl) countEl.textContent = selectedTags.length ? `${selectedTags.length} ${gt('selected')}` : '';
}

/* ── Panel actions (called from HTML) ──────────────── */
async function runSearchPane() {
  const q = document.getElementById('search-input').value.trim();
  if (!q) { toast(gt('enterQuery'), 'err'); return; }
  document.getElementById('nav-search').value = q;
  await doSearch(q);
}

async function runRecommend() {
  const input = document.getElementById('rec-input').value.trim();
  if (!input) { toast(gt('enterAnimeNameOrId'), 'err'); return; }
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
  if (!recs || !recs.length) { el.innerHTML = `<div class="empty-state">${gt('noResults')}</div>`; return; }
  el.innerHTML = recs.map(r => `
    <div class="rec-item" onclick="doSearchById(${r.id})">
      <div class="rec-name">${escHtml(r.name_cn || r.name)}</div>
      <div class="rec-expl">
        ${gt('tagsShort')}:${r.explanation.shared_tags} · ${gt('vaShort')}:${r.explanation.shared_voice_actors} · ${gt('studioShort')}:${r.explanation.shared_studios}
      </div>
    </div>
  `).join('');
}

async function runCasting() {
  if (!selectedTags.length) { toast(gt('selectAtLeastOneTag'), 'err'); return; }
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
            <div class="rec-expl">${gt('animeShort')}:${v.matched_anime_count} · ${gt('scoreShort')}:${v.summary_score.toFixed(1)}</div>
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
    loadGraph(data, false, false);
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
      <button class="btn btn-ghost btn-sm" onclick="expandCurrentNode()">${gt('expand')}</button>
      <button id="fav-btn" class="btn btn-sm ${isFaved ? 'btn-danger' : 'btn-ghost'}"
              onclick="toggleFavorite(${JSON.stringify(data).replace(/"/g,"'")})">
        ${isFaved ? gt('saved') : gt('save')}
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
        wrap.innerHTML = `<div class="rp-cover-ph" style="font-size:10px;font-family:var(--mono);color:var(--muted)">${gt('noCover')}</div>`;
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
    if (detail.date)     rows.push(infoRow(gt('date'), detail.date));
    if (detail.platform) rows.push(infoRow(gt('platform'), detail.platform));
    if (detail.episodes) rows.push(infoRow(gt('eps'), detail.episodes));
    if (detail.director) rows.push(infoRow(gt('director'), detail.director));
    if (detail.studios?.filter(Boolean).length)
      rows.push(infoRow(gt('studio'), detail.studios.filter(Boolean).join(', ')));
    if (detail.countries?.filter(Boolean).length)
      rows.push(infoRow(gt('country'), detail.countries.filter(Boolean).join(', ')));

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
          <div class="pane-label" style="margin-bottom:6px">${gt('summary')}</div>
          <div class="summary-text" id="summary-txt">${full}</div>
          ${detail.summary.length > 200 ? `<span class="summary-more" onclick="toggleSummary()">${gt('more')}</span>` : ''}
        </div>
      `;
    }

    infoEl.innerHTML = `
      <div class="info-rows">${rows.join('')}</div>
      ${tags.length ? `<div><div class="pane-label" style="margin-bottom:6px">${gt('tags')}</div>${tagHtml}</div>` : ''}
      ${summaryHtml}
    `;
  } catch {}

  // AI Ask widget
  const askWrap = document.getElementById('rp-ask-wrap');
  if (askWrap) {
    askWrap.innerHTML = `
      <div class="pane-label">${gt('aiQuery')}</div>
      <div class="ask-wrap">
        <textarea class="ask-ta" id="ask-input" placeholder="${gt('askPlaceholder')}" rows="2"></textarea>
        <div class="ask-foot">
          <span class="ask-src" id="ask-src"></span>
          <button class="btn btn-primary btn-sm" onclick="submitAsk(${animeId})">${gt('askBtn')}</button>
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
  if (btn) btn.textContent = el.classList.contains('expanded') ? gt('less') : gt('more');
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
      ${isFaved ? gt('saved') : gt('save')}
    </button>`;
  }

  scroll.innerHTML = `
    <div class="info-rows">
      ${infoRow(gt('type'), data.type)}
      ${infoRow(gt('id'), data.raw_id)}
    </div>
    <div class="rp-actions">
      <button class="btn btn-ghost btn-sm" onclick="expandCurrentNode()">${gt('expand')}</button>
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
      `/expand?id=${encodeURIComponent(rawId)}&type=${type}&display_lang=${currentLang}&limit=${expandLimit}`
    );
    loadGraph(data, false, false);
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
    loadGraph(data, false, false);
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
      toast(gt('removedFromFavorites'));
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
      toast(gt('savedToFavorites'), 'ok');
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
  btn.textContent = isFaved ? gt('saved') : gt('save');
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
      resp.textContent = body.error || gt('aiUnavailable');
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
      resp.textContent = gt('errorPrefix') + err.message;
    }
  }
}

/* ── Double-click focus ────────────────────────────── */
function onNodeDblTap(node) {
  _focusNodeId = node.id();
  // expand without fit
  const d = node.data();
  if (d.raw_id && d.type) doExpand(d.raw_id, d.type);
  // animate viewport to center on node
  cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.3), duration: 350 });
  // update visual depth hierarchy
  updateDepthStyles(node);
}

function updateDepthStyles(focusNode) {
  if (!cy) return;
  const depthMap = new Map();
  depthMap.set(focusNode.id(), 0);
  let frontier = [focusNode];
  for (let d = 1; d <= 2; d++) {
    const next = [];
    for (const n of frontier) {
      n.neighborhood('node').forEach(nb => {
        if (!depthMap.has(nb.id())) { depthMap.set(nb.id(), d); next.push(nb); }
      });
    }
    frontier = next;
  }
  cy.batch(() => {
    cy.nodes().forEach(n => {
      const depth = depthMap.has(n.id()) ? depthMap.get(n.id()) : 99;
      if (depth === 0) {
        n.style({ opacity: 1, 'border-width': 3, 'border-color': '#e07b54' });
      } else if (depth === 1) {
        n.style({ opacity: 0.9, 'border-width': 1.5, 'border-color': 'data(color)' });
      } else if (depth === 2) {
        n.style({ opacity: 0.6, 'border-width': 1.5, 'border-color': 'data(color)' });
      } else {
        n.style({ opacity: 0.25, 'border-width': 1.5, 'border-color': 'data(color)' });
      }
    });
  });
}

function resetDepthStyles() {
  if (!cy) return;
  _focusNodeId = null;
  cy.batch(() => {
    cy.nodes().forEach(n => n.style({ opacity: 1, 'border-width': 1.5, 'border-color': 'data(color)' }));
  });
}

/* ── Edge label toggle ─────────────────────────────── */
function toggleEdgeLabels() {
  showEdgeLabels = !showEdgeLabels;
  if (!cy) return;
  cy.edges().style('label',     showEdgeLabels ? (e => e.data('type') || '') : '');
  cy.edges().style('font-size', showEdgeLabels ? 8 : 0);
  const btn = document.getElementById('rel-toggle-btn');
  if (btn) btn.classList.toggle('active', showEdgeLabels);
}

/* ── Expand limit ──────────────────────────────────── */
function setExpandLimit(val) {
  expandLimit = parseInt(val, 10) || 20;
}

/* ── Graph toolbar ─────────────────────────────────── */
function fitGraph()    { if (cy) { cy.resize(); cy.fit(undefined, 40); } }
function clearGraph()  { if (cy) { cy.elements().remove(); resetDepthStyles(); updateGraphStats(); closeRightPanel(); } }
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

/* ═══════════════════════════════════════════════════════════
   Yoji AI Assistant
   ═══════════════════════════════════════════════════════════ */

let _yojiOpen  = false;
let _yojiAbort = null;

/* ── 显隐 ── */
function showYoji() {
  const root = document.getElementById('yoji-root');
  const btn  = document.getElementById('yoji-summon-btn');
  if (root) root.classList.remove('yoji-hidden');
  if (btn)  btn.classList.remove('active');
}

function hideYoji() {
  const root  = document.getElementById('yoji-root');
  const panel = document.getElementById('yoji-panel');
  const btn   = document.getElementById('yoji-summon-btn');
  if (root)  root.classList.add('yoji-hidden');
  if (panel) { panel.classList.remove('open'); panel.setAttribute('aria-hidden','true'); }
  if (btn)   btn.classList.add('active');
  _yojiOpen = false;
}

function toggleYojiPanel() {
  _yojiOpen = !_yojiOpen;
  const panel = document.getElementById('yoji-panel');
  if (!panel) return;
  panel.classList.toggle('open', _yojiOpen);
  panel.setAttribute('aria-hidden', String(!_yojiOpen));
  if (_yojiOpen) {
    setTimeout(() => {
      const inp = document.getElementById('yoji-input');
      if (inp) inp.focus();
    }, 220);
  }
}

function submitYojiAsk() {
  const input  = document.getElementById('yoji-input');
  const msgs   = document.getElementById('yoji-messages');
  const sendBtn = document.getElementById('yoji-send');
  if (!input || !msgs) return;

  const question = input.value.trim();
  if (!question) return;

  // Cancel any previous stream
  if (_yojiAbort) { _yojiAbort.abort(); }
  _yojiAbort = new AbortController();

  // Show user bubble
  const userBubble = document.createElement('div');
  userBubble.className = 'yoji-msg user';
  userBubble.textContent = question;
  msgs.appendChild(userBubble);

  // AI bubble (streaming)
  const intentEl = document.createElement('div');
  intentEl.className = 'yoji-intent-badge';
  intentEl.textContent = '…';

  const aiBubble = document.createElement('div');
  aiBubble.className = 'yoji-msg ai streaming';

  msgs.appendChild(intentEl);
  msgs.appendChild(aiBubble);
  msgs.scrollTop = msgs.scrollHeight;

  input.value = '';
  input.style.height = 'auto';
  if (sendBtn) sendBtn.disabled = true;

  (async () => {
    try {
      const res = await fetch(`${API_BASE}/rag/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
        signal: _yojiAbort.signal,
      });

      if (!res.ok) {
        aiBubble.textContent = 'Yoji is unavailable right now.';
        aiBubble.classList.remove('streaming');
        return;
      }

      const reader  = res.body.getReader();
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
            if (obj.meta) {
              const intent = obj.meta.intent || '';
              intentEl.textContent = intent === 'recommend' ? '✦ Recommend'
                                   : intent === 'relation'  ? '✦ Relation'
                                   : '✦ Factual';
            }
            if (obj.token) {
              aiBubble.textContent += obj.token;
              msgs.scrollTop = msgs.scrollHeight;
            }
            if (obj.done) {
              aiBubble.classList.remove('streaming');
            }
            if (obj.error) {
              aiBubble.textContent = obj.error;
              aiBubble.classList.remove('streaming');
            }
          } catch {}
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        aiBubble.textContent = 'Something went wrong. Try again.';
        aiBubble.classList.remove('streaming');
      }
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      msgs.scrollTop = msgs.scrollHeight;
    }
  })();
}

// Enter to send + 拖拽初始化
document.addEventListener('DOMContentLoaded', () => {
  // Enter to send (Shift+Enter = newline)
  const inp = document.getElementById('yoji-input');
  if (inp) {
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitYojiAsk();
      }
    });
  }

  // ── 拖拽 & 点击 ──────────────────────────────────────────
  const root   = document.getElementById('yoji-root');
  const handle = document.getElementById('yoji-handle');
  if (root && handle) {
    let dragging = false, hasMoved = false;
    let startX, startY, startL, startT;

    handle.addEventListener('mousedown', e => {
      if (e.button !== 0) return;
      // 首次拖动：把 bottom/right 转成 top/left
      const rect = root.getBoundingClientRect();
      root.style.bottom = 'auto';
      root.style.right  = 'auto';
      root.style.left   = rect.left + 'px';
      root.style.top    = rect.top  + 'px';

      dragging = true; hasMoved = false;
      startX = e.clientX; startY = e.clientY;
      startL = rect.left; startT = rect.top;
      root.classList.add('dragging');
      e.preventDefault();
    });

    document.addEventListener('mousemove', e => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasMoved = true;
      root.style.left = Math.max(0, Math.min(window.innerWidth  - root.offsetWidth,  startL + dx)) + 'px';
      root.style.top  = Math.max(0, Math.min(window.innerHeight - root.offsetHeight, startT + dy)) + 'px';
    });

    document.addEventListener('mouseup', () => {
      if (dragging) { dragging = false; root.classList.remove('dragging'); }
    });

    // 点击：只有没有拖动才触发聊天窗
    handle.addEventListener('click', () => {
      if (!hasMoved) toggleYojiPanel();
      hasMoved = false;
    });
  }

  // 背景去除：自动采样角落颜色 → flood fill 删除相似背景色
  // 支持棋盘格/纯白/纯灰等各种背景，人物内部颜色不受影响
  const yojiImg = document.querySelector('.yoji-avatar');
  if (yojiImg) {
    const doRemove = () => {
      try {
        const canvas = document.createElement('canvas');
        const ctx    = canvas.getContext('2d');
        const W = yojiImg.naturalWidth;
        const H = yojiImg.naturalHeight;
        canvas.width = W; canvas.height = H;
        ctx.drawImage(yojiImg, 0, 0);

        const imgData = ctx.getImageData(0, 0, W, H);
        const d       = imgData.data;
        const visited = new Uint8Array(W * H);

        // 采样角落 + 四边中点，收集背景色样本
        const pts = [
          [0,0],[1,0],[0,1],[2,0],[0,2],
          [W-1,0],[W-2,0],[0,H-1],[0,H-2],[W-1,H-1],
          [W>>1, 0],[0, H>>1],[W-1, H>>1],[W>>1, H-1],
        ];
        const samples = pts.map(([x,y]) => {
          const i = (y * W + x) * 4;
          return [d[i], d[i+1], d[i+2]];
        });

        // 与任意一个背景样本的曼哈顿距离 < 阈值 → 视为背景
        const THRESH = 110; // 每通道约 37，足以区分灰色棋格和人物颜色
        function isBg(x, y) {
          const i = (y * W + x) * 4;
          const r = d[i], g = d[i+1], b = d[i+2];
          return samples.some(([sr, sg, sb]) =>
            Math.abs(r - sr) + Math.abs(g - sg) + Math.abs(b - sb) < THRESH
          );
        }

        // BFS flood fill 从四边出发
        const queue = [];
        function enqueue(x, y) {
          if (x < 0 || x >= W || y < 0 || y >= H) return;
          const idx = y * W + x;
          if (visited[idx] || !isBg(x, y)) return;
          visited[idx] = 1;
          queue.push(x, y);
        }

        for (let x = 0; x < W; x++) { enqueue(x, 0); enqueue(x, H-1); }
        for (let y = 0; y < H; y++) { enqueue(0, y); enqueue(W-1, y); }

        let qi = 0;
        while (qi < queue.length) {
          const x = queue[qi++], y = queue[qi++];
          d[(y * W + x) * 4 + 3] = 0; // 全透明
          enqueue(x+1, y); enqueue(x-1, y);
          enqueue(x, y+1); enqueue(x, y-1);
        }

        ctx.putImageData(imgData, 0, 0);
        yojiImg.src = canvas.toDataURL('image/png');
      } catch (e) {
        console.warn('[Yoji] bg-removal failed:', e.message);
      }
    };
    if (yojiImg.complete && yojiImg.naturalWidth) doRemove();
    else yojiImg.addEventListener('load', doRemove);
  }
});

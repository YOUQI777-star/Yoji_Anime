/* ═══════════════════════════════════════════════════════
   YOJI — Shared utilities
   Auth · API · Modal · Toast · Nav
═══════════════════════════════════════════════════════ */

const API_BASE = window.API_BASE || 'http://localhost:8080';

/* ── Auth ──────────────────────────────────────────── */
function getToken()  { return localStorage.getItem('yoji_token') || ''; }
function setToken(t) { localStorage.setItem('yoji_token', t); }
function getUser()   { try { return JSON.parse(localStorage.getItem('yoji_user')); } catch { return null; } }
function setUser(u)  { localStorage.setItem('yoji_user', JSON.stringify(u)); }
function isLoggedIn(){ return !!getToken(); }
function clearAuth() { localStorage.removeItem('yoji_token'); localStorage.removeItem('yoji_user'); }

/* ── API fetch ─────────────────────────────────────── */
async function apiFetch(path, opts = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.error || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/* ── Toast ─────────────────────────────────────────── */
function toast(msg, type = 'info') {
  let c = document.getElementById('toast-wrap');
  if (!c) {
    c = document.createElement('div');
    c.id = 'toast-wrap';
    document.body.appendChild(c);
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

/* ── Nav user area ─────────────────────────────────── */
function renderNavUser(containerId = 'nav-user') {
  const wrap = document.getElementById(containerId);
  if (!wrap) return;
  const user = getUser();
  if (user) {
    const initial = (user.display_name || user.email || '?')[0].toUpperCase();
    wrap.innerHTML = `<a class="user-avatar" href="profile.html" title="${user.display_name}">${initial}</a>`;
  } else {
    wrap.innerHTML = `<button class="btn btn-ghost btn-sm" onclick="showAuthModal('login')">SIGN IN</button>`;
  }
}

/* ── Modal ─────────────────────────────────────────── */
function showAuthModal(tab = 'login') {
  ensureModal();
  document.getElementById('modal-overlay').classList.add('open');
  switchModalTab(tab);
}

function hideAuthModal() {
  const el = document.getElementById('modal-overlay');
  if (el) el.classList.remove('open');
}

function switchModalTab(tab) {
  document.querySelectorAll('.modal-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.modal-form').forEach(f =>
    f.style.display = f.dataset.form === tab ? 'flex' : 'none');
  document.querySelectorAll('.modal-err').forEach(e =>
    e.classList.remove('show'));
}

function ensureModal() {
  if (document.getElementById('modal-overlay')) return;
  const div = document.createElement('div');
  div.innerHTML = `
<div id="modal-overlay">
  <div id="modal-box">
    <div class="modal-head">
      <span class="modal-title">// ACCESS CONTROL</span>
      <button class="modal-x" onclick="hideAuthModal()">×</button>
    </div>
    <div class="modal-tabs">
      <button class="modal-tab active" data-tab="login"    onclick="switchModalTab('login')">LOGIN</button>
      <button class="modal-tab"        data-tab="register" onclick="switchModalTab('register')">REGISTER</button>
    </div>

    <!-- Login -->
    <form data-form="login" class="modal-form" style="display:flex;flex-direction:column" onsubmit="submitLogin(event)">
      <div class="modal-body">
        <div class="form-group">
          <span class="label">Email</span>
          <input id="l-email" class="input" type="email" placeholder="user@domain.com" autocomplete="email" required />
        </div>
        <div class="form-group">
          <span class="label">Password</span>
          <input id="l-pass" class="input" type="password" placeholder="••••••••" autocomplete="current-password" required />
        </div>
        <span id="login-err" class="modal-err"></span>
      </div>
      <div style="padding:0 18px 18px">
        <button type="submit" class="btn btn-primary btn-full">AUTHENTICATE →</button>
      </div>
    </form>

    <!-- Register -->
    <form data-form="register" class="modal-form" style="display:none;flex-direction:column" onsubmit="submitRegister(event)">
      <div class="modal-body">
        <div class="form-group">
          <span class="label">Email</span>
          <input id="r-email" class="input" type="email" placeholder="user@domain.com" autocomplete="email" required />
        </div>
        <div class="form-group">
          <span class="label">Display Name</span>
          <input id="r-name" class="input" type="text" placeholder="your name" autocomplete="nickname" />
        </div>
        <div class="form-group">
          <span class="label">Password</span>
          <input id="r-pass" class="input" type="password" placeholder="min 6 chars" autocomplete="new-password" required minlength="6" />
        </div>
        <span id="reg-err" class="modal-err"></span>
      </div>
      <div style="padding:0 18px 18px">
        <button type="submit" class="btn btn-primary btn-full">CREATE ACCOUNT →</button>
      </div>
    </form>
  </div>
</div>`;
  document.body.appendChild(div.firstElementChild);
  // close on backdrop click
  document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target.id === 'modal-overlay') hideAuthModal();
  });
}

async function submitLogin(e) {
  e.preventDefault();
  const errEl = document.getElementById('login-err');
  errEl.classList.remove('show');
  const email = document.getElementById('l-email').value.trim();
  const pass  = document.getElementById('l-pass').value;
  try {
    const data = await apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password: pass })
    });
    setToken(data.token);
    setUser(data.user);
    hideAuthModal();
    renderNavUser();
    toast('AUTHENTICATED', 'ok');
    if (typeof window.onAuthSuccess === 'function') window.onAuthSuccess(data.user);
  } catch (err) {
    errEl.textContent = err.message.toUpperCase();
    errEl.classList.add('show');
  }
}

async function submitRegister(e) {
  e.preventDefault();
  const errEl = document.getElementById('reg-err');
  errEl.classList.remove('show');
  const email = document.getElementById('r-email').value.trim();
  const name  = document.getElementById('r-name').value.trim();
  const pass  = document.getElementById('r-pass').value;
  try {
    const data = await apiFetch('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, display_name: name, password: pass })
    });
    setToken(data.token);
    setUser(data.user);
    hideAuthModal();
    renderNavUser();
    toast('REGISTERED', 'ok');
    if (typeof window.onAuthSuccess === 'function') window.onAuthSuccess(data.user);
  } catch (err) {
    errEl.textContent = err.message.toUpperCase();
    errEl.classList.add('show');
  }
}

async function doLogout() {
  try { await apiFetch('/auth/logout', { method: 'POST' }); } catch {}
  clearAuth();
  toast('LOGGED OUT');
  window.location.href = 'index.html';
}

/* ── Init (call on each page) ──────────────────────── */
function initShared() {
  ensureModal();
  renderNavUser();
}

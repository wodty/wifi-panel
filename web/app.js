/* wifi-panel 前端：连接 / 面板列表 / 编辑器 / 遥控台 */
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const store = {
  get token() { return localStorage.getItem("panel_token") || ""; },
  set token(v) { localStorage.setItem("panel_token", v); },
};

const state = {
  profiles: [],
  profile: null,        // 当前打开的 profile 对象
  editing: false,
  sel: null,            // 选中的 element
  ws: null,
  wsTimer: null,
};

/* ---------- 视图切换 ---------- */
function show(view) {
  for (const id of ["view-connect", "view-profiles", "view-remote"]) {
    $("#" + id).hidden = id !== view;
  }
}

/* ---------- API ---------- */
async function api(path, opts = {}) {
  opts.headers = Object.assign({ "X-Token": store.token }, opts.headers || {});
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, opts);
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
  return res.json();
}

/* ---------- 连接页 ---------- */
$("#btn-connect").addEventListener("click", async () => {
  const t = $("#token-input").value.trim();
  if (!t) return;
  store.token = t;
  try {
    await api("/api/ping");
    await loadProfiles();
    show("view-profiles");
  } catch (e) {
    $("#connect-err").textContent = e.message === "unauthorized" ? "令牌错误" : "无法连接服务: " + e.message;
  }
});

$("#btn-logout").addEventListener("click", () => {
  store.token = "";
  show("view-connect");
});

/* ---------- 电视设置 ---------- */
const TV_HINTS = {
  adb: "ADB：电视上开启 设置 → 关于 → 连点「版本号/软件版本」→ 开发者选项 → 网络调试。首次连接电视会弹授权，勾选「一律允许」。",
  samsung: "三星：首次连接电视会弹出「允许」提示，确认后令牌自动保存。",
  lg: "LG webOS：首次连接电视屏幕会弹出「允许」，确认后配对密钥自动保存。",
};
const TV_DEFAULT_PORTS = { adb: 5555, samsung: 8001, lg: 3000 };

async function tvSave() {
  await api("/api/tv", { method: "PUT", body: {
    ip: $("#tv-ip").value.trim(),
    port: +$("#tv-port").value || TV_DEFAULT_PORTS[$("#tv-protocol").value],
    protocol: $("#tv-protocol").value,
  }});
}

$("#tv-protocol").addEventListener("change", () => {
  $("#tv-protocol-hint").textContent = TV_HINTS[$("#tv-protocol").value] || "";
  $("#tv-port").value = TV_DEFAULT_PORTS[$("#tv-protocol").value];
});

$("#btn-tv").addEventListener("click", async () => {
  $("#tv-sheet").hidden = false;
  $("#tv-status").textContent = "";
  try {
    const s = await api("/api/tv");
    $("#tv-protocol").value = s.cfg.protocol || "adb";
    $("#tv-ip").value = s.cfg.ip || "";
    $("#tv-port").value = s.cfg.port || TV_DEFAULT_PORTS[s.cfg.protocol || "adb"];
    $("#tv-protocol-hint").textContent = TV_HINTS[$("#tv-protocol").value] || "";
    if (!s.adb_installed && s.protocol === "adb") {
      $("#tv-status").textContent = "状态：中枢未安装 adb（Docker 镜像已内置，本机试跑需自行安装）";
    } else {
      $("#tv-status").textContent = s.online ? "状态：已连接 " + s.serial : "状态：未连接";
    }
  } catch (e) {
    $("#tv-status").textContent = "加载失败：" + e.message;
  }
});

$("#tv-close").addEventListener("click", () => { $("#tv-sheet").hidden = true; });

$("#tv-save").addEventListener("click", async () => {
  try { await tvSave(); toast("已保存"); }
  catch (e) { $("#tv-status").textContent = "保存失败：" + e.message; }
});

$("#tv-test").addEventListener("click", async () => {
  try {
    await tvSave();
    $("#tv-status").textContent = "连接中…（首次连接请在电视上确认授权）";
    const r = await api("/api/tv/connect", { method: "POST" });
    $("#tv-status").textContent = (r.ok ? "已连接： " : "连接失败： ") + (r.msg || "");
  } catch (e) {
    $("#tv-status").textContent = "连接失败：" + e.message;
  }
});

/* ---------- 面板列表 ---------- */
async function loadProfiles() {
  const data = await api("/api/profiles");
  state.profiles = data.profiles;
  const box = $("#profile-list");
  box.innerHTML = "";
  if (!state.profiles.length) {
    box.innerHTML = `<div class="empty">还没有面板<br>
      <button class="primary" id="btn-seed" style="margin-top:12px">用默认通用面板</button></div>`;
    $("#btn-seed").onclick = () => createFromTemplate("universal");
  }
  for (const p of state.profiles) {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `<span class="name"></span>
      <button class="small use">使用</button>
      <button class="small edit">编辑</button>
      <button class="small ghost del">删</button>`;
    const nameEl = div.querySelector(".name");
    nameEl.textContent = p.name;
    if (p.id === "default") {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "默认";
      nameEl.appendChild(tag);
    }
    div.querySelector(".use").onclick = () => openProfile(p.id, false);
    div.querySelector(".edit").onclick = () => openProfile(p.id, true);
    div.querySelector(".del").onclick = async () => {
      if (!confirm(`删除面板「${p.name}」？`)) return;
      await api("/api/profiles/" + p.id, { method: "DELETE" });
      loadProfiles();
    };
    box.appendChild(div);
  }
}

/* ---------- 模板（清单由服务端提供，前端不重复定义）---------- */
async function loadTemplates() {
  const box = $("#tpl-list");
  box.innerHTML = '<p class="hint left">加载中…</p>';
  try {
    const data = await api("/api/templates");
    box.innerHTML = "";
    for (const t of data.templates) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tpl-item";
      const main = document.createElement("span");
      main.className = "tpl-main";
      const nameRow = document.createElement("span");
      nameRow.className = "tpl-name";
      nameRow.textContent = t.name;
      if (t.default) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "默认";
        nameRow.appendChild(tag);
      }
      const desc = document.createElement("span");
      desc.className = "tpl-desc";
      desc.textContent = t.desc;
      main.append(nameRow, desc);
      btn.appendChild(main);
      btn.onclick = () => createFromTemplate(t.kind);
      box.appendChild(btn);
    }
  } catch (e) {
    box.innerHTML = "";
    const p = document.createElement("p");
    p.className = "err";
    p.textContent = "模板加载失败：" + e.message;
    box.appendChild(p);
  }
}

async function createFromTemplate(kind) {
  try {
    const r = await api("/api/templates/" + encodeURIComponent(kind), { method: "POST", body: {} });
    $("#tpl-sheet").hidden = true;
    await loadProfiles();
    // 空白模板进编辑模式直接搭；其他模板先进使用模式，改按钮再点「编辑」
    openProfile(r.id, kind === "blank");
  } catch (e) {
    toast("创建失败：" + e.message);
  }
}

$("#btn-new").addEventListener("click", async () => {
  $("#tpl-sheet").hidden = false;
  await loadTemplates();
});
$("#tpl-close").addEventListener("click", () => { $("#tpl-sheet").hidden = true; });
$("#tpl-sheet").addEventListener("click", (e) => {
  if (e.target.id === "tpl-sheet") $("#tpl-sheet").hidden = true;
});


/* ---------- 打开面板 ---------- */
async function openProfile(id, edit) {
  try {
    state.profile = await api("/api/profiles/" + id);
  } catch (e) {
    toast(e.message === "unauthorized" ? "请重新输入令牌" : "面板加载失败：" + e.message);
    loadProfiles();
    return;
  }
  state.editing = edit;
  $("#profile-title").textContent = state.profile.name || id;
  $("#btn-toggle-edit").textContent = edit ? "使用" : "编辑";
  $("#edit-tools").hidden = !edit;
  $("#cfg").hidden = true;
  closeWs();
  renderStage();
  show("view-remote");
  openWs();
  if (!edit && window.innerWidth < window.innerHeight) {
    // 竖屏玩手柄体验差，提示但不强制
    if (state.profile.elements.some(e => e.type === "button")) toast("建议横屏使用");
  }
}

$("#btn-back").addEventListener("click", () => {
  if (state.editing && confirm("未保存的修改将丢失，返回？")) {} else if (state.editing) return;
  closeWs(); loadProfiles(); show("view-profiles");
});

$("#btn-toggle-edit").addEventListener("click", () => {
  state.editing = !state.editing;
  state.sel = null;
  $("#cfg").hidden = true;
  $("#btn-toggle-edit").textContent = state.editing ? "使用" : "编辑";
  $("#edit-tools").hidden = !state.editing;
  renderStage();
});

$("#btn-save").addEventListener("click", async () => {
  await api("/api/profiles/" + state.profile.id, { method: "PUT", body: state.profile });
  toast("已保存");
});

$("#edit-tools").querySelectorAll("[data-add]").forEach((b) => {
  b.addEventListener("click", () => {
    const type = b.dataset.add;
    const el = type === "touchpad"
      ? { id: "e" + Date.now(), type, x: 10, y: 50, w: 80, h: 30 }
      : { id: "e" + Date.now(), type: "button", label: "键", x: 40, y: 55, w: 14, h: 14, shape: "rect", color: "#378add", action: { type: "key", key: "space", mode: "tap", mods: [] } };
    state.profile.elements.push(el);
    renderStage();
    select(el);
  });
});

/* ---------- 舞台渲染 ---------- */
function renderStage() {
  const stage = $("#stage");
  stage.classList.toggle("editing", state.editing);
  stage.innerHTML = "";
  for (const el of state.profile.elements) {
    stage.appendChild(makeElement(el));
  }
}

function makeElement(el) {
  const div = document.createElement("div");
  div.className = "el " + el.type + (el.shape === "round" ? " round" : "");
  div.style.left = el.x + "%"; div.style.top = el.y + "%";
  div.style.width = el.w + "%"; div.style.height = el.h + "%";
  if (el.type === "button") {
    div.textContent = el.label || "";
    if (el.color) div.style.background = el.color + "";
  }
  div.dataset.id = el.id;
  bindElement(div, el);
  return div;
}

function elById(id) { return state.profile.elements.find(e => e.id === id); }

function vibrate(ms) { try { navigator.vibrate && navigator.vibrate(ms); } catch (_) {} }

/* ---------- 元素交互 ---------- */
function bindElement(div, el) {
  if (state.editing) {
    bindEditorDrag(div, el);
  } else if (el.type === "button") {
    bindUseButton(div, el);
  } else if (el.type === "touchpad") {
    bindTouchpad(div);
  }
}

function bindUseButton(div, el) {
  div.addEventListener("contextmenu", (e) => e.preventDefault());
  div.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    div.setPointerCapture(e.pointerId);
    div.classList.add("held");
    vibrate(8);
    sendAction(el);
  });
  const up = () => { div.classList.remove("held"); sendUp(el); };
  div.addEventListener("pointerup", up);
  div.addEventListener("pointercancel", up);
}

function sendAction(el) {
  const a = el.action || {};
  if (a.type === "key") {
    if (a.mode === "hold") send({ t: "key_down", key: a.key });
    else send({ t: "key_tap", key: a.key, mods: a.mods || [] });
  } else if (a.type === "mouse_click") {
    send({ t: "mouse_click", button: a.button || "left" });
  } else if (a.type === "media") {
    send({ t: "media", action: a.action });
  } else if (a.type === "adb_key") {
    send({ t: "adb", action: { kind: "key", key: a.key } });
  } else if (a.type === "adb_app") {
    send({ t: "adb", action: { kind: "app", package: a.package } });
  }
}

function sendUp(el) {
  const a = el.action || {};
  if (a.type === "key" && a.mode === "hold") send({ t: "key_up", key: a.key });
}

/* 触控板：单指移动=鼠标；单指轻点=左键；双指移动=滚动；双指轻点=右键 */
function bindTouchpad(div) {
  const pointers = new Map();
  div.addEventListener("contextmenu", (e) => e.preventDefault());
  div.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    div.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, t: Date.now() });
  });
  div.addEventListener("pointermove", (e) => {
    const p = pointers.get(e.pointerId);
    if (!p) return;
    if (pointers.size === 1) {
      send({ t: "mouse_move", dx: Math.round(e.clientX - p.x), dy: Math.round(e.clientY - p.y) });
    } else if (pointers.size === 2) {
      const dy = Math.round((e.clientY - p.y) / 10);
      if (dy) send({ t: "scroll", dy });
    }
    p.x = e.clientX; p.y = e.clientY;
  });
  const up = (e) => {
    const p = pointers.get(e.pointerId);
    pointers.delete(e.pointerId);
    if (!p) return;
    const dt = Date.now() - p.t;
    const dist = Math.hypot(e.clientX - p.sx, e.clientY - p.sy);
    if (dt < 250 && dist < 12) {
      vibrate(8);
      send({ t: "mouse_click", button: pointers.size >= 1 ? "right" : "left" });
    }
  };
  div.addEventListener("pointerup", up);
  div.addEventListener("pointercancel", up);
}

/* ---------- 编辑器拖动 ---------- */
function bindEditorDrag(div, el) {
  let start = null, moved = false;
  div.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    div.setPointerCapture(e.pointerId);
    start = { px: e.clientX, py: e.clientY, x: el.x, y: el.y };
    moved = false;
  });
  div.addEventListener("pointermove", (e) => {
    if (!start) return;
    const rect = $("#stage").getBoundingClientRect();
    const dx = (e.clientX - start.px) / rect.width * 100;
    const dy = (e.clientY - start.py) / rect.height * 100;
    if (Math.abs(dx) + Math.abs(dy) > 0.5) moved = true;
    el.x = clamp(Math.round((start.x + dx) * 2) / 2, 0, 100 - el.w);
    el.y = clamp(Math.round((start.y + dy) * 2) / 2, 0, 100 - el.h);
    div.style.left = el.x + "%"; div.style.top = el.y + "%";
  });
  const up = () => {
    if (start && !moved) select(el);
    start = null;
  };
  div.addEventListener("pointerup", up);
  div.addEventListener("pointercancel", () => { start = null; });
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

/* ---------- 配置抽屉 ---------- */
const KEY_LIST = ["space","enter","tab","esc","backspace","delete","up","down","left","right",
  "home","end","page_up","page_down","f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12"];

function select(el) {
  state.sel = el;
  $("#stage").querySelectorAll(".el").forEach(d => d.classList.toggle("sel", d.dataset.id === el.id));
  renderCfg();
  $("#cfg").hidden = false;
}

function renderCfg() {
  const el = state.sel, box = $("#cfg");
  if (!el) { box.hidden = true; return; }
  const a = el.action || {};
  let actionHtml = "";
  if (el.type === "button") {
    actionHtml = `
      <div class="row">
        <div><label>动作类型</label>
          <select id="c-type">
            <option value="key">键盘</option>
            <option value="mouse_click">鼠标点击</option>
            <option value="media">媒体</option>
            <option value="adb_key">电视按键</option>
            <option value="adb_app">电视启动应用</option>
          </select>
        </div>
        <div><label>触发模式</label>
          <select id="c-mode"><option value="tap">单击</option><option value="hold">按住持续</option></select>
        </div>
      </div>
      <div class="row" id="row-key">
        <div><label>按键</label><input id="c-key" list="keys" value="${esc(a.key || "")}"><datalist id="keys">
          ${KEY_LIST.map(k => `<option value="${k}">`).join("")}</datalist></div>
        <div><label>修饰键(可多选)</label><div class="row">
          ${["ctrl","shift","alt"].map(m => `<button class="small mod ${((a.mods)||[]).includes(m) ? "primary" : ""}" data-mod="${m}">${m}</button>`).join("")}
        </div></div>
      </div>
      <div class="row" id="row-mouse" hidden>
        <div><label>鼠标键</label><select id="c-button">
          <option value="left">左键</option><option value="right">右键</option><option value="middle">中键</option>
        </select></div>
      </div>
      <div class="row" id="row-media" hidden>
        <div><label>媒体动作</label><select id="c-media">
          <option value="volume_up">音量+</option><option value="volume_down">音量-</option>
          <option value="mute">静音</option><option value="play_pause">播放/暂停</option>
        </select></div>
      </div>
      <div class="row" id="row-adbkey" hidden>
        <div><label>电视按键</label><select id="c-akey">
          ${["dpad_up","dpad_down","dpad_left","dpad_right","ok","enter","back","home","menu",
             "volume_up","volume_down","mute","power","wake","sleep","play_pause","media_previous","media_next"]
            .map(k => `<option value="${k}">${k}</option>`).join("")}
        </select></div>
      </div>
      <div class="row" id="row-adbapp" hidden>
        <div><label>应用包名</label><input id="c-apkg" placeholder="com.tcl.android.tv" value="${a.package || ""}"></div>
      </div>`;
  }
  box.innerHTML = `
    <button class="ghost small close" id="c-close">收起</button>
    <div class="row">
      <div><label>标签</label><input id="c-label" value="${el.label || ""}"></div>
      <div><label>宽度 %</label><input id="c-w" type="number" value="${el.w}" min="4" max="100"></div>
      <div><label>高度 %</label><input id="c-h" type="number" value="${el.h}" min="4" max="100"></div>
    </div>
    <div class="row">
      <div><label>颜色</label><select id="c-color">
        ${[["#378add","蓝"],["#639922","绿"],["#e24b4a","红"],["#854f0b","橙"],["#534AB7","紫"],["#888780","灰"]]
          .map(([v, n]) => `<option value="${v}" ${el.color === v ? "selected" : ""}>${n}</option>`).join("")}
      </select></div>
      <div><label>形状</label><select id="c-shape">
        <option value="rect" ${el.shape !== "round" ? "selected" : ""}>方形</option>
        <option value="round" ${el.shape === "round" ? "selected" : ""}>圆形</option>
      </select></div>
    </div>
    ${actionHtml}
    <div class="row-actions">
      <button id="c-del" class="danger">删除元素</button>
    </div>`;

  const refreshActionType = () => {
    const t = $("#c-type").value;
    $("#row-key").hidden = t !== "key";
    $("#row-mouse").hidden = t !== "mouse_click";
    $("#row-media").hidden = t !== "media";
    $("#row-adbkey").hidden = t !== "adb_key";
    $("#row-adbapp").hidden = t !== "adb_app";
    $("#c-mode").disabled = t !== "key";
  };
  if (el.type === "button") {
    $("#c-type").value = a.type || "key";
    $("#c-mode").value = a.mode || "tap";
    if (a.button) $("#c-button").value = a.button;
    if (a.action) $("#c-media").value = a.action;
    if (a.key && a.type && a.type.startsWith("adb")) $("#c-akey").value = a.key;
    refreshActionType();
    $("#c-type").onchange = refreshActionType;
    box.querySelectorAll(".mod").forEach(b => b.addEventListener("click", () => b.classList.toggle("primary")));
  }
  $("#c-close").onclick = () => { $("#cfg").hidden = true; state.sel = null;
    $("#stage").querySelectorAll(".el").forEach(d => d.classList.remove("sel")); };
  $("#c-del").onclick = () => {
    state.profile.elements = state.profile.elements.filter(e => e.id !== el.id);
    $("#cfg").hidden = true; state.sel = null; renderStage();
  };
  // 字段变更实时写回
  const on = (id, ev, fn) => { const n = $(id); if (n) n.addEventListener(ev, fn); };
  on("#c-label", "input", () => { el.label = $("#c-label").value; renderStage(); });
  on("#c-w", "input", () => { el.w = clamp(+$("#c-w").value || 10, 4, 100); });
  on("#c-h", "input", () => { el.h = clamp(+$("#c-h").value || 10, 4, 100); });
  on("#c-color", "change", () => { el.color = $("#c-color").value; renderStage(); });
  on("#c-shape", "change", () => { el.shape = $("#c-shape").value; renderStage(); });
  if (el.type === "button") {
    const writeAction = () => {
      const t = $("#c-type").value;
      const mods = [...box.querySelectorAll(".mod.primary")].map(b => b.dataset.mod);
      if (t === "key") el.action = { type: "key", key: $("#c-key").value.trim().toLowerCase(), mode: $("#c-mode").value, mods };
      else if (t === "mouse_click") el.action = { type: "mouse_click", button: $("#c-button").value };
      else if (t === "media") el.action = { type: "media", action: $("#c-media").value };
      else if (t === "adb_key") el.action = { type: "adb_key", key: $("#c-akey").value };
      else if (t === "adb_app") el.action = { type: "adb_app", package: $("#c-apkg").value.trim() };
    };
    ["#c-key", "#c-mode", "#c-button", "#c-media", "#c-akey", "#c-apkg"].forEach(id => on(id, "input", writeAction));
    ["#c-mode", "#c-button", "#c-media", "#c-key", "#c-akey", "#c-apkg", "#c-type"].forEach(id => on(id, "change", writeAction));
    box.querySelectorAll(".mod").forEach(b => b.addEventListener("click", writeAction));
  }
}

/* ---------- WebSocket ---------- */
function openWs() {
  closeWs();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/remote?token=${encodeURIComponent(store.token)}`);
  state.ws = ws;
  ws.onopen = () => $("#ws-dot").classList.replace("off", "on");
  ws.onclose = () => { $("#ws-dot").classList.replace("on", "off"); };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.t === "agent_status") setAgentDot(msg.online);
      if (msg.t === "error" && msg.msg === "agent_offline") toast("PC Agent 未连接");
      if (msg.t === "tv_result" && !msg.ok) toast(msg.msg || "电视指令失败");
    } catch (_) {}
  };
  state.wsTimer = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: "ping" }));
  }, 5000);
}

function closeWs() {
  if (state.wsTimer) { clearInterval(state.wsTimer); state.wsTimer = null; }
  if (state.ws) { try { state.ws.close(); } catch (_) {} state.ws = null; }
  $("#ws-dot").classList.replace("on", "off");
}

function setAgentDot(on) { $("#agent-dot").classList.toggle("on", on); $("#agent-dot").classList.toggle("off", !on); }

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(obj));
  }
}

/* ---------- 杂项 ---------- */
let toastTimer = null;
function toast(text) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast";
    t.style.cssText = "position:fixed;left:50%;top:14%;transform:translateX(-50%);background:#000c;color:#fff;padding:8px 16px;border-radius:8px;font-size:14px;z-index:99";
    document.body.appendChild(t); }
  t.textContent = text; t.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.style.display = "none"; }, 1800);
}

document.addEventListener("contextmenu", (e) => e.preventDefault());
document.addEventListener("gesturestart", (e) => e.preventDefault());

/* 启动：已有令牌则直接进列表 */
(async function init() {
  if (store.token) {
    try {
      const r = await api("/api/ping");
      setAgentDot(r.agent_online);
      await loadProfiles();
      show("view-profiles");
      return;
    } catch (_) { /* 掉到连接页 */ }
  }
  show("view-connect");
})();

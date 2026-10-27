/* TPAgent web UI: login, sessions, WebSocket task loop, file panel. Vanilla JS. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { token: localStorage.getItem("tpagent_token") || "", session: null, ws: null, running: false, sessions: [] };

  // ---------- API ----------
  async function api(path, opts = {}) {
    const headers = Object.assign({ Authorization: "Bearer " + state.token }, opts.headers || {});
    const r = await fetch(path, Object.assign({}, opts, { headers }));
    if (r.status === 401) { logout(); throw new Error("Token sai hoặc hết hạn"); }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || ("Lỗi " + r.status));
    return r.status === 204 ? null : r.json();
  }
  const fileUrl = (path, inline) =>
    `/api/files/${state.session}/download?path=${encodeURIComponent(path)}&token=${encodeURIComponent(state.token)}${inline ? "&inline=1" : ""}`;

  // ---------- auth ----------
  async function login(token) {
    state.token = token;
    await api("/api/me");
    localStorage.setItem("tpagent_token", token);
    $("login").classList.add("hidden");
    $("app").classList.remove("hidden");
    await refreshSessions();
    const last = localStorage.getItem("tpagent_session");
    if (last && state.sessions.some((s) => s.id === last)) openSession(last);
  }
  function disconnect() {
    const ws = state.ws;
    state.ws = null;
    if (ws) { ws.onclose = null; ws.close(); }
  }
  function logout() {
    localStorage.removeItem("tpagent_token");
    state.token = "";
    disconnect();
    $("app").classList.add("hidden");
    $("login").classList.remove("hidden");
  }
  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    try { await login($("login-token").value.trim()); } catch (err) { $("login-error").textContent = err.message; }
  });
  $("btn-logout").addEventListener("click", logout);

  // ---------- sessions ----------
  async function refreshSessions() {
    state.sessions = (await api("/api/sessions")).sessions;
    const ul = $("session-list");
    ul.innerHTML = "";
    for (const s of state.sessions) {
      const li = document.createElement("li");
      li.className = (s.id === state.session ? "active" : "") + (s.running ? " running" : "");
      const title = document.createElement("span"); title.className = "s-title"; title.textContent = s.title;
      const meta = document.createElement("span"); meta.className = "s-meta"; meta.textContent = fmtDate(s.mtime) + (s.cost_usd ? ` · $${s.cost_usd.toFixed(3)}` : "");
      const del = document.createElement("button"); del.className = "s-del"; del.title = "Xóa phiên"; del.textContent = "🗑";
      del.addEventListener("click", (e) => { e.stopPropagation(); deleteSession(s.id); });
      li.append(title, meta, del);
      li.addEventListener("click", () => { openSession(s.id); closeDrawers(); });
      ul.appendChild(li);
    }
  }
  function fmtDate(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  }
  async function newSession() {
    const { id } = await api("/api/sessions", { method: "POST" });
    await refreshSessions();
    openSession(id);
    closeDrawers();
  }
  async function deleteSession(id) {
    if (!confirm("Xóa phiên này và toàn bộ file của nó?")) return;
    await api(`/api/sessions/${id}`, { method: "DELETE" });
    if (state.session === id) { state.session = null; disconnect(); Chat.clear(); $("session-title").textContent = "Chưa chọn phiên"; }
    await refreshSessions();
  }
  async function openSession(id) {
    disconnect();
    state.session = id;
    localStorage.setItem("tpagent_session", id);
    const info = state.sessions.find((s) => s.id === id);
    $("session-title").textContent = info ? info.title : id;
    const detail = await api(`/api/sessions/${id}`);
    Chat.renderHistory(detail.messages);
    setCost(detail.cost_usd);
    setRunning(detail.running);
    await refreshSessions();
    loadFiles();
    connect();
  }
  $("btn-new").addEventListener("click", () => newSession().catch(showErr));

  // ---------- websocket ----------
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/${state.session}?token=${encodeURIComponent(state.token)}`);
    state.ws = ws;
    ws.onopen = () => $("status-dot").classList.add("on");
    ws.onclose = () => { $("status-dot").classList.remove("on", "busy"); if (state.ws === ws) setTimeout(() => { if (state.ws === ws && state.session) connect(); }, 2000); };
    ws.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  }
  function send(obj) {
    if (!state.ws || state.ws.readyState !== 1) { showErr("Chưa kết nối tới server"); return false; }
    state.ws.send(JSON.stringify(obj));
    return true;
  }
  function onEvent(ev) {
    switch (ev.type) {
      case "status": setRunning(ev.running); setCost(ev.total_usd); break;
      case "start": setRunning(true); Chat.addSystem(`Model: ${ev.model} (${ev.provider})`); break;
      case "cost": setCost(ev.total_usd); break;
      case "text_delta": Chat.delta(ev.text ?? ev.delta ?? ""); break;
      case "text": if (!Chat.endStream(ev.text)) Chat.addAssistant(ev.text); break;
      case "tool_call": Chat.addToolCall(ev.id, ev.name, ev.args); break;
      case "tool_result": Chat.setToolResult(ev.id, ev.name, ev.text, ev.is_error, ev.has_image); loadFiles(); break;
      case "approval_request":
        Chat.addApproval(ev, (ans) => send({ type: "approval_response", id: ev.id, approved: ans.approved, always: ans.always }));
        notify("TPAgent cần anh duyệt: " + ev.tool);
        break;
      case "question":
        Chat.addQuestion(ev, (text) => send({ type: "answer", id: ev.id, text }));
        notify("TPAgent hỏi: " + ev.question);
        break;
      case "done":
        if (!Chat.endStream(ev.text)) Chat.addAssistant(ev.text);
        setCost(ev.total_usd); setRunning(false); refreshSessions(); loadFiles();
        notify("TPAgent đã xong");
        break;
      case "cancelled": Chat.endStream(); Chat.addSystem("Đã dừng."); setCost(ev.total_usd); setRunning(false); break;
      case "error": Chat.endStream(); Chat.addSystem("Lỗi: " + ev.message, true); setRunning(false); break;
      case "queued": Chat.addSystem(ev.message); break;
      case "pong": break;
      default: console.debug("event", ev);
    }
  }
  function setRunning(on) {
    state.running = !!on;
    $("btn-cancel").classList.toggle("hidden", !on);
    $("btn-send").disabled = !!on;
    $("status-dot").classList.toggle("busy", !!on);
  }
  function setCost(v) { if (typeof v === "number") $("cost-badge").textContent = "$" + v.toFixed(4); }
  function notify(text) {
    if (document.hasFocus() || !("Notification" in window) || Notification.permission !== "granted") return;
    try { new Notification("TPAgent", { body: text }); } catch (e) { /* ignore */ }
  }

  // ---------- composer ----------
  const input = $("input");
  function submit() {
    const text = input.value.trim();
    if (!text || state.running) return;
    if (!state.session) { newSession().then(submit).catch(showErr); return; }
    if (!send({ type: "task", text, tier: $("tier").value || null, auto_approve: $("auto-approve").checked })) return;
    Chat.addUser(text);
    input.value = ""; autosize();
    setRunning(true);
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  }
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
  $("btn-send").addEventListener("click", submit);
  $("btn-cancel").addEventListener("click", () => send({ type: "cancel" }));
  $("tier").value = localStorage.getItem("tpagent_tier") || "";
  $("tier").addEventListener("change", () => localStorage.setItem("tpagent_tier", $("tier").value));
  $("auto-approve").checked = localStorage.getItem("tpagent_auto") === "1";
  $("auto-approve").addEventListener("change", () => localStorage.setItem("tpagent_auto", $("auto-approve").checked ? "1" : "0"));

  // ---------- files ----------
  const IMG = /\.(png|jpe?g|gif|webp)$/i, VID = /\.(mp4|webm|mov)$/i;
  async function loadFiles() {
    if (!state.session) return;
    let files = [];
    try { files = (await api(`/api/files/${state.session}`)).files; } catch (e) { return; }
    const ul = $("file-list");
    ul.innerHTML = "";
    for (const f of files) {
      const li = document.createElement("li");
      const depth = f.path.split("/").length - 1;
      li.style.paddingLeft = (6 + depth * 14) + "px";
      const name = document.createElement("span"); name.className = "f-name" + (f.is_dir ? " f-dir" : "");
      name.textContent = (f.is_dir ? "📁 " : "📄 ") + f.name;
      if (!f.is_dir) name.addEventListener("click", () => preview(f.path));
      li.appendChild(name);
      if (!f.is_dir) {
        const size = document.createElement("span"); size.className = "f-size"; size.textContent = fmtSize(f.size);
        const a = document.createElement("a"); a.href = fileUrl(f.path, false); a.textContent = "⬇"; a.title = "Tải về"; a.download = f.name;
        li.append(size, a);
      }
      ul.appendChild(li);
    }
  }
  function fmtSize(n) { return n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB"; }
  function preview(path) {
    const box = $("preview");
    box.innerHTML = "";
    if (IMG.test(path)) { const img = document.createElement("img"); img.src = fileUrl(path, true); img.alt = path; box.appendChild(img); }
    else if (VID.test(path)) { const v = document.createElement("video"); v.src = fileUrl(path, true); v.controls = true; box.appendChild(v); }
    else { const a = document.createElement("a"); a.href = fileUrl(path, false); a.textContent = "Tải " + path; a.download = ""; box.appendChild(a); }
  }
  async function upload(fileList) {
    if (!state.session) { await newSession(); }
    const fd = new FormData();
    for (const f of fileList) fd.append("files", f, f.name);
    $("upload-progress").textContent = `Đang tải ${fileList.length} file…`;
    try {
      const r = await api(`/api/files/${state.session}`, { method: "POST", body: fd });
      $("upload-progress").textContent = "Đã tải: " + r.saved.join(", ");
      Chat.addSystem("Đã tải lên: " + r.saved.join(", "));
      loadFiles();
    } catch (e) { $("upload-progress").textContent = "Lỗi: " + e.message; }
  }
  const dz = $("dropzone");
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); e.stopPropagation(); dz.classList.remove("over"); if (e.dataTransfer.files.length) upload(e.dataTransfer.files); });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files.length) { openFiles(true); upload(e.dataTransfer.files); } });
  $("file-input").addEventListener("change", (e) => { if (e.target.files.length) upload(e.target.files); e.target.value = ""; });

  // ---------- drawers ----------
  function openFiles(on) { $("app").classList.toggle("files-open", on); if (on) loadFiles(); }
  function closeDrawers() { $("app").classList.remove("menu-open"); $("backdrop").classList.add("hidden"); }
  $("btn-files").addEventListener("click", () => openFiles(!$("app").classList.contains("files-open")));
  $("btn-files-close").addEventListener("click", () => openFiles(false));
  $("btn-menu").addEventListener("click", () => { $("app").classList.add("menu-open"); $("backdrop").classList.remove("hidden"); });
  $("backdrop").addEventListener("click", closeDrawers);
  function showErr(e) { Chat.addSystem("Lỗi: " + (e.message || e), true); }

  // ---------- boot ----------
  if (state.token) login(state.token).catch(() => logout()); else logout();
})();

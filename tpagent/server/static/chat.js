/* Chat rendering: bubbles, streaming text, tool cards, approval/question cards. */
(function () {
  "use strict";
  const chat = document.getElementById("chat");
  const empty = document.getElementById("empty");
  let streaming = null;      // current assistant bubble receiving text_delta
  let streamBuf = "";
  const toolCards = new Map(); // tool_call id -> <details>

  function md(text) {
    if (window.marked && window.DOMPurify) {
      try {
        return DOMPurify.sanitize(marked.parse(text || "", { breaks: true, gfm: true }));
      } catch (e) { /* fall through to <pre> */ }
    }
    const div = document.createElement("div");
    div.className = "plain";
    div.textContent = text || "";
    return div.outerHTML;
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function shouldStick() {
    return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 120;
  }

  function append(node) {
    const stick = shouldStick();
    empty.classList.add("hidden");
    chat.appendChild(node);
    if (stick) chat.scrollTop = chat.scrollHeight;
    return node;
  }

  function clear() {
    for (const n of [...chat.children]) if (n !== empty) n.remove();
    empty.classList.remove("hidden");
    streaming = null; streamBuf = ""; toolCards.clear();
  }

  function addUser(text) {
    return append(el("div", "msg user", text));
  }

  function addAssistant(text) {
    endStream();
    if (!text || !text.trim()) return null;
    const n = el("div", "msg assistant");
    n.innerHTML = md(text);
    return append(n);
  }

  function delta(chunk) {
    if (!streaming) {
      streaming = append(el("div", "msg assistant streaming"));
      streamBuf = "";
    }
    const stick = shouldStick();
    streamBuf += chunk;
    streaming.innerHTML = md(streamBuf);
    if (stick) chat.scrollTop = chat.scrollHeight;
  }

  /* Finish the streaming bubble; `finalText` (from "text"/"done") replaces the buffer if given. */
  function endStream(finalText) {
    if (!streaming) return false;
    const text = finalText !== undefined ? finalText : streamBuf;
    streaming.classList.remove("streaming");
    if (text && text.trim()) streaming.innerHTML = md(text); else streaming.remove();
    streaming = null; streamBuf = "";
    return true;
  }

  function addSystem(text, isError) {
    return append(el("div", "sys" + (isError ? " err" : ""), text));
  }

  function shortArgs(args) {
    if (!args || typeof args !== "object") return "";
    if (typeof args.command === "string") return args.command;
    return Object.entries(args).map(([k, v]) => `${k}=${String(v).replace(/\s+/g, " ").slice(0, 60)}`).join(", ");
  }

  function addToolCall(id, name, args) {
    endStream();
    const d = el("details", "tool");
    const s = el("summary");
    s.append(el("span", "name", name), el("span", "short", shortArgs(args)), el("span", "state", "⏳"));
    const body = el("div", "body");
    const argsPre = el("pre", "args", JSON.stringify(args ?? {}, null, 1));
    body.append(el("div", "muted", "Tham số"), argsPre);
    d.append(s, body);
    toolCards.set(id, d);
    return append(d);
  }

  function setToolResult(id, name, text, isError, hasImage) {
    let d = toolCards.get(id);
    if (!d) d = addToolCall(id, name, {});
    d.querySelector(".state").textContent = isError ? "✖" : "✔";
    if (isError) d.classList.add("error");
    const lines = (text || "(không có kết quả)").split("\n");
    const head = lines.slice(0, 40).join("\n") + (lines.length > 40 ? `\n… (+${lines.length - 40} dòng)` : "");
    const body = d.querySelector(".body");
    body.append(el("div", "muted", "Kết quả" + (hasImage ? " (có ảnh)" : "")), el("pre", "result", head));
    const short = d.querySelector(".short");
    if (!short.textContent && lines[0]) short.textContent = lines[0].slice(0, 80);
    return d;
  }

  function addApproval(req, onAnswer) {
    endStream();
    const n = document.getElementById("tpl-approval").content.firstElementChild.cloneNode(true);
    n.dataset.id = req.id;
    n.querySelector(".tool").textContent = req.tool;
    n.querySelector(".args").textContent = typeof req.args?.command === "string" ? req.args.command : JSON.stringify(req.args ?? {}, null, 1);
    n.addEventListener("click", (e) => {
      const act = e.target.dataset?.act;
      if (!act) return;
      const approved = act !== "deny";
      onAnswer({ approved, always: act === "always" });
      resolveCard(n, approved ? (act === "always" ? "Đã cho phép (luôn luôn cho tool này)" : "Đã cho phép") : "Đã từ chối");
    });
    return append(n);
  }

  function addQuestion(q, onAnswer) {
    endStream();
    const n = document.getElementById("tpl-question").content.firstElementChild.cloneNode(true);
    n.dataset.id = q.id;
    n.querySelector(".q").textContent = q.question;
    const opts = n.querySelector(".options");
    for (const o of q.options || []) {
      const b = el("button", "btn small", o);
      b.addEventListener("click", () => { onAnswer(o); resolveCard(n, "Trả lời: " + o); });
      opts.appendChild(b);
    }
    const free = n.querySelector(".free");
    const send = () => {
      const t = free.value.trim();
      if (!t) return;
      onAnswer(t); resolveCard(n, "Trả lời: " + t);
    };
    n.querySelector('[data-act="send"]').addEventListener("click", send);
    free.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); send(); } });
    append(n);
    free.focus();
    return n;
  }

  function resolveCard(n, verdict) {
    n.classList.add("resolved");
    n.appendChild(el("div", "verdict", verdict));
  }

  function resolveById(id, verdict) {
    const n = chat.querySelector(`.card[data-id="${id}"]`);
    if (n && !n.classList.contains("resolved")) resolveCard(n, verdict);
  }

  /* Rebuild the transcript from saved messages (user / assistant+tool_calls / tool). */
  function renderHistory(messages) {
    clear();
    for (const m of messages || []) {
      if (m.role === "user") addUser(typeof m.content === "string" ? m.content : JSON.stringify(m.content));
      else if (m.role === "assistant") {
        if (m.content) addAssistant(m.content);
        for (const c of m.tool_calls || []) addToolCall(c.id, c.name, c.args);
      } else if (m.role === "tool") setToolResult(m.tool_call_id, m.name, m.content, m.is_error, false);
    }
    chat.scrollTop = chat.scrollHeight;
  }

  window.Chat = { clear, addUser, addAssistant, delta, endStream, addSystem, addToolCall, setToolResult,
                  addApproval, addQuestion, resolveById, renderHistory };
})();

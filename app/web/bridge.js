/* The link between this page and the toolbox (web_ui.py, web_state.py).

   Python -> page: LS.render(state) about 3 times a second while the window is shown, with
     state.header (title bar and sidebar) and state.pages[<page>] (one part per page).
   Page -> Python: LS.act(name, ...args) runs a registered action on the toolbox's thread.

   A page script registers itself with LS.page(name, render), where name is the app's page name
   ("Players", "Cheat check", "Duels", "Chat", "Status", "Help") and render(pageState, state)
   draws it. Pages only redraw what changed: keep focus and scroll where they are. */
(function () {
  const PAGE_IDS = {"Players": "players", "Cheat check": "cheat", "Duels": "duels", "Chat": "chat",
                    "Status": "status", "Help": "help"};
  const NAMES = Object.fromEntries(Object.entries(PAGE_IDS).map(([k, v]) => [v, k]));
  const renderers = {};
  // The title bar's lights: the data keeps its names, the label says what each one is.
  const LIGHT_LABELS = {"History": "Bans", "Lists": "Cheater lists"};
  // Sidebar badges are neutral; red only on the pages whose badge counts cheaters.
  const RED_BADGES = new Set(["Players", "Cheat check"]);
  let current = null;

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  function act(name, ...args) {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api.act(name, args);
    console.log("act (no app):", name, args);  // opened as a plain file: nothing to call
  }

  function openPage(name) {
    const id = PAGE_IDS[name] || "players";
    document.querySelectorAll(".nav").forEach(n => n.classList.toggle("on", n.dataset.p === id));
    document.querySelectorAll(".page").forEach(p => p.classList.toggle("on", p.id === "p-" + id));
  }

  function go(name) {  // open a page at once, then the app remembers it
    current = name;
    openPage(name);
    act("show_page", name);
  }

  function header(h) {
    const count = document.querySelector(".tcount");
    // "10/24 players" once status gave the server's slots (the mockup's look), else the list's count.
    const slots = /^(\d+)\/(\d+)$/.exec(h.slots || "");
    if (count) count.innerHTML = (slots ? `<b>${slots[1]}</b>/${slots[2]}` : `<b>${h.players}</b>`) + " players" +
                                 (h.map ? " &middot; " + esc(h.map) : "") +
                                 (h.server ? ` &middot; <span class="tserver" title="${esc(h.hostname)}">${esc(h.server)}</span>` : "");
    const lights = document.querySelector(".lights");
    if (lights) lights.innerHTML = h.lights.map(l =>
      `<span class="light" title="${esc(LIGHT_LABELS[l.name] || l.name)}: ${esc(l.state)}" data-light="${esc(l.name)}">` +
      `<span class="dot ${l.dot === "ok" ? "" : l.dot === "warn" ? "warn" : l.dot === "bad" ? "red" : "off"}"></span>` +
      `${esc(LIGHT_LABELS[l.name] || l.name)}${l.dot === "ok" && l.name !== "Lists" ? "" : ` <small>${esc(l.name === "Lists" && /known/.test(l.state) ? l.state.split(" ")[0] : l.state)}</small>`}</span>`).join("");
    document.querySelectorAll(".lights .light").forEach(el => el.onclick = () => go("Status"));
    const hint = document.querySelector(".hint");
    if (hint) hint.innerHTML = `<span class="kbd">${esc(h.toggle_key)}</span>show / hide`;
    let fb = document.getElementById("feedback");
    if (!fb) {
      fb = document.createElement("span");
      fb.id = "feedback";
      fb.style.cssText = "font-family:var(--f-num);font-size:12px;color:var(--ac);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:420px";
      const space = document.querySelector(".tspace");
      if (space) space.before(fb);
    }
    fb.textContent = h.feedback || "";
    document.querySelectorAll(".nav").forEach(n => {
      const name = NAMES[n.dataset.p];
      let badge = n.querySelector(".badge");
      const value = h.badges[name];
      if (value) {
        if (!badge) { badge = document.createElement("span"); n.appendChild(badge); }
        badge.className = RED_BADGES.has(name) ? "badge r" : "badge";
        badge.textContent = value;
      } else if (badge) badge.remove();
    });
    const foot = document.querySelector(".side-foot");
    if (foot) foot.innerHTML = `<div>SESSION <b>${esc(h.foot.session)}</b></div><div>MAP <b>${esc(h.foot.map)}</b></div>` +
                               `<div class="fserver" title="${esc(h.foot.server)}">SERVER <b>${esc(h.foot.server)}</b></div>` +
                               `<div>PING <b>${esc(h.foot.ping)}</b></div>`;
    if (h.page !== current) { current = h.page; openPage(h.page); }
  }

  function render(state) {
    window.LS.state = state;
    try { header(state.header); } catch (e) { console.error("header", e); }
    for (const [name, fn] of Object.entries(renderers)) {
      const part = state.pages[name];
      if (part === undefined) continue;
      try { fn(part, state); } catch (e) { console.error(name, e); }
    }
  }

  function ready() {
    document.querySelectorAll(".nav").forEach(n => n.onclick = () => go(NAMES[n.dataset.p]));
    const [min, max, close] = document.querySelectorAll(".wbtns .wbtn");
    if (min) min.onclick = () => act("hide");
    if (max) max.onclick = () => act("maximize");
    if (close) close.onclick = () => act("quit");
    // A text box takes the keyboard from the game only while you type in it.
    document.addEventListener("focusin", e => { if (e.target.matches("input, textarea")) act("keyboard", true); });
    document.addEventListener("focusout", e => { if (e.target.matches("input, textarea")) act("keyboard", false); });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && document.activeElement) document.activeElement.blur(); });
  }

  window.LS = {state: null, render, act, ready, esc, openPage, go,
               page(name, fn) { renderers[name] = fn; }};
})();

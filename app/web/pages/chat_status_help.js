/* Page script: the Chat, Status and Help pages (state from web_chat_status_help.py).
   Each page builds its skeleton once and then only changes what changed, so a hover preview,
   focus or scroll position survives the redraws. */
(function () {
  const esc = s => LS.esc(s);
  const usage = u => `${esc(u[0])}${u[1] ? ` <em>${esc(u[1])}</em>` : ""}`;
  const pillUsage = u => `<span>${usage(u)}</span>`;  // one flex item, so <name> stays by its command
  const setText = (el, text) => { if (el && el.textContent !== String(text)) el.textContent = text; };
  const setHTML = (el, html) => { if (el && el._html !== html) { el._html = html; el.innerHTML = html; } };
  const setSwitch = (sw, on) => {
    if (!sw) return;
    sw.dataset.on = on ? "1" : "0";
    sw.setAttribute("aria-checked", on ? "true" : "false");
    setText(sw.nextElementSibling, on ? "ON" : "OFF");
  };
  const keyable = (el, fn) => {  // a switch also answers Space and Enter, like the mockup's
    el.onkeydown = e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); fn(); } };
  };

  // ---------------------------------------------------------------- Chat
  const WHO_COLOURS = {you: "#99ccff", red: "#ff8a83", console: "var(--ac)"};
  const TEXT_COLOURS = {you: "var(--tx)", red: "var(--tx)", feed: "var(--tx2)", console: "var(--ac)"};
  let chatState = null;

  function previewLine([who, colour, text]) {
    const name = who ? `<span class="pw" style="color:${colour === "feed" ? "var(--tx2)" : WHO_COLOURS[colour]}">${esc(who)} :</span> ` : "";
    return `<div class="pl">${name}<span style="color:${TEXT_COLOURS[colour] || "var(--tx)"}">${esc(text)}</span></div>`;
  }

  function hoverPreview(row, key) {
    let timer = null, jobs = [], box = null;
    const hide = () => {
      clearTimeout(timer); timer = null;
      jobs.forEach(clearTimeout); jobs = [];
      if (box) { box.remove(); box = null; }
    };
    const show = () => {
      const lines = (chatState && chatState.examples[key]) || [];
      box = document.createElement("div");
      box.className = "cpreview";
      box.innerHTML = `<div class="cpl">Example: what it posts in chat</div>`;
      row.appendChild(box);
      lines.forEach((line, n) => jobs.push(setTimeout(() => box && box.insertAdjacentHTML("beforeend", previewLine(line)),
                                                     n * chatState.preview_step)));
    };
    row.addEventListener("mouseenter", () => {
      if (!timer && !box) timer = setTimeout(() => { timer = null; show(); }, chatState ? chatState.preview_delay : 1000);
    });
    row.addEventListener("mouseleave", hide);
  }

  function chatSkeleton(root, s) {
    root.innerHTML = `
      <div class="ph"><h1>Chat</h1><span class="crumb">// what the scanner says in game chat</span></div>
      <div class="pad">
        <div class="row" style="align-items:flex-start">
          <div class="pnl brk" id="chat-sets">
            ${s.settings.map(x => `
            <div class="set" data-key="${esc(x.key)}"><div class="st"><b></b><span>${esc(x.about)}</span></div>
              <span class="sw" data-on="0" role="switch" tabindex="0"></span><span class="swtxt">OFF</span></div>`).join("")}
            <div class="set" data-key="muted"><div class="st"><b>!speak: muted players</b><span>Players you muted in their panel (Mute !speak). Click to unmute them all.</span></div><span class="val"></span></div>
          </div>
          <div class="pnl" style="flex:.7">
            <div class="pnl-h"><span class="lab">Last posts</span></div>
            <div class="pnl-b chatlog" id="chat-posts"></div>
          </div>
        </div>
        <div class="pnl">
          <div class="pnl-h"><span class="lab">Chat commands</span><span class="num" style="margin-left:auto;font-size:11px;color:var(--tx3)">What anyone can type in chat. Click one to switch it off or on. The Help page says what each one does.</span></div>
          <div class="pnl-b"><div class="pills" id="chat-pills">
            ${s.commands.map(c => `<button class="pill" data-id="${esc(c.id)}">${pillUsage(c.usage)}<span class="o">OFF</span></button>`).join("")}
          </div></div>
        </div>
      </div>`;
    root.querySelectorAll("#chat-sets .set").forEach(row => {
      const key = row.dataset.key;
      if (key === "muted") { row.onclick = () => LS.act("unmute_all_speak"); return; }
      const sw = row.querySelector(".sw");
      const flip = () => { setSwitch(sw, sw.dataset.on !== "1"); LS.act("chat_toggle", key); };
      row.onclick = e => { if (!e.target.closest(".cpreview")) flip(); };
      keyable(sw, flip);
      const example = s.settings.find(x => x.key === key).example;
      if (example) hoverPreview(row, example);
    });
    root.querySelectorAll("#chat-pills .pill").forEach(p => p.onclick = () => {
      p.classList.toggle("on");  // at once; the next state confirms it
      setText(p.querySelector(".o"), p.classList.contains("on") ? "ON" : "OFF");
      LS.act("chat_command", p.dataset.id);
    });
    root._built = s.commands.map(c => c.id).join() + "|" + s.settings.map(x => x.key).join();
  }

  LS.page("Chat", s => {
    const root = document.getElementById("p-chat");
    if (!root || s.error) return;
    chatState = s;
    if (root._built !== s.commands.map(c => c.id).join() + "|" + s.settings.map(x => x.key).join()) chatSkeleton(root, s);
    for (const x of s.settings) {
      const row = root.querySelector(`.set[data-key="${x.key}"]`);
      setText(row.querySelector(".st b"), x.title);
      setSwitch(row.querySelector(".sw"), x.on);
    }
    const val = root.querySelector('.set[data-key="muted"] .val');
    setText(val, s.muted ? `${s.muted} muted` : "nobody");
    val.classList.toggle("on", !!s.muted);
    for (const c of s.commands) {
      const p = root.querySelector(`.pill[data-id="${c.id}"]`);
      p.classList.toggle("on", c.on);
      setText(p.querySelector(".o"), c.on ? "ON" : "OFF");
    }
    setHTML(document.getElementById("chat-posts"), s.posts.length
      ? s.posts.map(t => `<div><span class="a">[scanner]</span> ${esc(t)}</div>`).join("")
      : `<div class="t">Nothing said in chat yet this session.</div>`);
  });

  // ---------------------------------------------------------------- Status
  const DOTS = {ok: "", warn: "warn", off: "off", bad: "red"};
  const ST = {ok: "ok", warn: "wn", off: "off", bad: "bd"};

  LS.page("Status", s => {
    const root = document.getElementById("p-status");
    if (!root || s.error) return;
    if (!root._built) {
      root._built = true;
      root.innerHTML = `
        <div class="ph"><h1>Status</h1><span class="crumb">// system check</span><span style="flex:1"></span>
          <span class="sw" id="hud-sw" data-on="0" role="switch" tabindex="0" title="One thin line at the top of your screen: the enemy line-up, their Medics (MEDIC DOWN - PUSH) and their Spies."></span><span class="swtxt">OFF</span><span style="font-weight:500">Mini HUD</span><button class="btn sm" id="hud-move" title="Press, drag the line where you can read it, then press Done.">Move</button></div>
        <div class="pad">
          <div><span class="lab">Connections</span></div>
          <div class="conn" id="st-conn" style="margin-top:-8px"></div>
          <div class="row" style="align-items:flex-start">
            <div style="display:flex;flex-direction:column;gap:16px">
              <div class="pnl">
                <div class="pnl-h"><span class="lab">Chat this session</span></div>
                <div class="kpis two" id="st-chat"></div>
              </div>
              <div class="pnl brk">
                <div class="pnl-h"><span class="lab">Keys</span></div>
                <div class="keys" id="st-keys"></div>
              </div>
            </div>
            <div class="pnl">
              <div class="pnl-h"><span class="lab">Is everything working?</span><span class="num" id="st-ok" style="margin-left:auto;font-size:11px"></span></div>
              <div id="st-health"></div>
            </div>
          </div>
        </div>`;
      const sw = document.getElementById("hud-sw");
      const flip = () => { setSwitch(sw, sw.dataset.on !== "1"); LS.act("hud_toggle"); };
      sw.onclick = flip;
      keyable(sw, flip);
      document.getElementById("hud-move").onclick = () => LS.act("hud_move");
    }
    setSwitch(document.getElementById("hud-sw"), s.hud);
    const move = document.getElementById("hud-move");
    setText(move, s.hud_moving ? "Done" : "Move");
    move.classList.toggle("pri", s.hud_moving);
    setHTML(document.getElementById("st-conn"), s.connections.map(c =>
      `<div><div class="top"><span class="dot ${DOTS[c.dot] ?? "red"}"></span>${esc(c.name)}</div>` +
      `<div class="st ${ST[c.dot] ?? "bd"}">${esc(c.state)}</div><div class="sub">${esc(c.about)}</div></div>`).join(""));
    setHTML(document.getElementById("st-chat"),
      `<div><b>${s.chat.sent}</b><span>Sent</span></div><div><b>${s.chat.refused}</b><span>Refused by the server</span></div>`);
    setHTML(document.getElementById("st-keys"), s.keys.map(([k, about]) =>
      `<div class="keyrow"><span class="kbd">${esc(k)}</span>${esc(about)}</div>`).join(""));
    const ok = document.getElementById("st-ok");
    setText(ok, `${s.health_ok} / ${s.health.length} OK`);
    ok.style.color = s.health_ok === s.health.length ? "var(--grn)" : "#ffb070";
    setHTML(document.getElementById("st-health"), s.health.map(h =>
      `<div class="chk"><span class="dot ${DOTS[h.level] ?? "off"}"></span>${esc(h.name)}` +
      `<span class="r ${h.level === "warn" ? "w" : h.level === "bad" ? "b" : ""}">${esc(h.text)}</span></div>`).join(""));
  });

  // ---------------------------------------------------------------- Help
  function helpCard(c) {
    const cls = c.id === "keys" ? "pnl hc brk" : c.id === "info" ? "pnl hc wide" : "pnl hc";
    const body = c.id === "info" ? ` style="display:grid;grid-template-columns:1fr 1fr;column-gap:24px"` : "";
    let rows = "", eg = "";
    for (const r of c.rows) {
      let about = r.about;
      const m = about.match(/^(.*?)\s*Example: (\S+ \S+)(.*)$/);  // "!speak russian hello" goes in its own box
      if (m) { about = m[1]; eg = `<div class="eg"><b>${esc(m[2])}</b>${esc(m[3])}</div>`; }
      rows += r.usage[0] ? `<div class="cmd"><code>${usage(r.usage)}</code><span>${esc(about)}</span></div>`
                         : `<div class="hp">${esc(about)}</div>`;
    }
    const note = c.note ? `<div class="hnote">${esc(c.note)}</div>` : "";
    return `<div class="${cls}" data-card="${esc(c.id)}"><div class="pnl-h"><span class="lab">${esc(c.title)}</span></div>` +
           `<div class="pnl-b"${body}>${rows}${eg}</div>${note}</div>`;
  }

  LS.page("Help", s => {
    const root = document.getElementById("p-help");
    if (!root || s.error) return;
    if (!root._built) {
      root._built = true;
      root.innerHTML = `<div class="ph"><h1>Help</h1><span class="crumb">// keys and chat commands</span></div>` +
                       `<div class="pad"><div class="hgrid" id="help-grid"></div></div>`;
    }
    setHTML(document.getElementById("help-grid"), s.cards.map(helpCard).join(""));
  });
})();

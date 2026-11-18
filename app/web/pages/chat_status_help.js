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
      <div class="ph"><h1>Chat</h1><span class="crumb">// what the toolbox says in game chat</span></div>
      <div class="pad">
        <div class="row" style="align-items:flex-start">
          <div class="pnl brk" id="chat-sets">
            ${s.settings.map(x => `
            <div class="set" data-key="${esc(x.key)}"><div class="st"><b></b><span>${esc(x.about)}</span></div>
              <span class="sw" data-on="0" role="switch" tabindex="0"></span><span class="swtxt">OFF</span></div>`).join("")}
            <div class="set" data-key="muted"><div class="st"><b>!speak: blocked players</b><span>Players whose !speak you blocked in their panel (Block their !speak). Click to let them all use it again.</span></div><span class="val"></span></div>
          </div>
          <div class="pnl" style="flex:.7">
            <div class="pnl-h"><span class="lab">Last posts</span><span class="num" id="chat-count" title="This session: lines that reached the chat, and lines the server refused (TF2's spam limit)"></span></div>
            <div class="pnl-b chatlog" id="chat-posts"></div>
          </div>
        </div>
        <div class="pnl">
          <div class="pnl-h"><span class="lab">Chat commands</span><span class="phint">What anyone can type in chat. Hover one to see what it does, click it to switch it off or on.</span></div>
          <div class="pnl-b"><div class="pills" id="chat-pills">
            ${s.commands.map(c => `<button class="pill" data-id="${esc(c.id)}" aria-label="${esc(c.usage.join(" ").trim())}: ${esc(c.about)}">${pillUsage(c.usage)}<span class="o">OFF</span><span class="ptip" role="tooltip">${esc(c.about)}</span></button>`).join("")}
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
    setText(val, s.muted ? `${s.muted} blocked` : "nobody");
    val.classList.toggle("on", !!s.muted);
    for (const c of s.commands) {
      const p = root.querySelector(`.pill[data-id="${c.id}"]`);
      p.classList.toggle("on", c.on);
      setText(p.querySelector(".o"), c.on ? "ON" : "OFF");
    }
    setHTML(document.getElementById("chat-posts"), s.posts.length
      ? s.posts.map(t => `<div><span class="a">[toolbox]</span> ${esc(t)}</div>`).join("")
      : `<div class="t">Nothing said in chat yet this session.</div>`);
    const count = document.getElementById("chat-count");
    setText(count, `${s.sent} sent · ${s.refused} refused`);
    count.classList.toggle("bad", s.refused > 0);
  });

  // ---------------------------------------------------------------- Status
  const DOTS = {ok: "", warn: "warn", off: "off", bad: "red"};
  const ST = {ok: "ok", warn: "wn", off: "off", bad: "bd"};

  // One compact row of two cards: the connections, and is everything working.
  LS.page("Status", s => {
    const root = document.getElementById("p-status");
    if (!root || s.error) return;
    if (!root._built) {
      root._built = true;
      root.innerHTML = `
        <div class="ph"><h1>Status</h1><span class="crumb">// is everything working</span></div>
        <div class="pad">
          <div class="srow">
            <div class="pnl brk">
              <div class="pnl-h"><span class="lab">Connections</span><span class="num sok" id="st-conn-ok"></span></div>
              <div class="slist" id="st-conn"></div>
            </div>
            <div class="pnl">
              <div class="pnl-h"><span class="lab">Is everything working?</span><span class="num sok" id="st-ok"></span></div>
              <div class="slist" id="st-health"></div>
            </div>
          </div>
        </div>`;
    }
    const line = (dot, name, text, sub) =>
      `<div class="sline"><span class="dot ${DOTS[dot] ?? "red"}"></span><b>${esc(name)}</b>` +
      `<span class="st ${ST[dot] ?? "bd"}">${esc(text)}${sub ? `<small>${esc(sub)}</small>` : ""}</span></div>`;
    // Only a connection that isn't OK says what it is needed for.
    setHTML(document.getElementById("st-conn"), s.connections.map(c =>
      line(c.dot, c.label || c.name, c.state, c.dot === "ok" ? "" : `needed for ${c.about}`)).join(""));
    const bad = s.connections.filter(c => c.dot !== "ok").length;
    const cok = document.getElementById("st-conn-ok");
    setText(cok, bad ? `${s.connections.length - bad} / ${s.connections.length} OK` : "all OK");
    cok.classList.toggle("w", !!bad);
    const ok = document.getElementById("st-ok");
    setText(ok, `${s.health_ok} / ${s.health.length} OK`);
    ok.classList.toggle("w", s.health_ok !== s.health.length);
    setHTML(document.getElementById("st-health"), s.health.map(h => line(h.level, h.name, h.text, "")).join(""));
  });

  // ---------------------------------------------------------------- Help
  // A short manual: one scrollable column of sections.
  function helpSection(c) {
    let rows = "", eg = "";
    for (const r of c.rows) {
      let about = r.about;
      const m = about.match(/^(.*?)\s*Example: (\S+ \S+)(.*)$/);  // "!speak russian hello" goes in its own box
      if (m) { about = m[1]; eg = `<div class="eg">Example: <b>${esc(m[2])}</b>${esc(m[3])}</div>`; }
      rows += r.usage[0] ? `<div class="cmd"><code>${usage(r.usage)}</code><span>${esc(about)}</span></div>`
                         : `<div class="hp">${esc(about)}</div>`;
    }
    if (c.link) rows += `<p class="hp">${esc(c.link.text)}</p>` +
                        `<button class="btn sm hlink" data-page="${esc(c.link.page)}">Open the ${esc(c.link.page)} page` +
                        `<svg viewBox="0 0 16 16"><path d="M3 8h10M9 4l4 4-4 4"/></svg></button>`;
    const note = c.note ? `<p class="hnote">${esc(c.note)}</p>` : "";
    return `<section class="hsec" data-card="${esc(c.id)}"><h2>${esc(c.title)}</h2>${rows}${eg}${note}</section>`;
  }

  LS.page("Help", s => {
    const root = document.getElementById("p-help");
    if (!root || s.error) return;
    if (!root._built) {
      root._built = true;
      root.innerHTML = `<div class="ph"><h1>Help</h1><span class="crumb">// keys and chat commands</span></div>` +
                       `<div class="pad"><div class="pnl brk hman" id="help-man"></div></div>`;
      root.addEventListener("click", e => {  // "Open the Chat page": where the information commands are
        const link = e.target.closest(".hlink");
        if (link) LS.go(link.dataset.page);
      });
    }
    setHTML(document.getElementById("help-man"), s.cards.map(helpSection).join(""));
  });
})();

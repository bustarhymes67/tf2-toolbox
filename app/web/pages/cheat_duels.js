/* Page script: the Cheat check and Duels pages (state from web_cheat_duels.py).
   Each page builds its skeleton once; every part is redrawn only when its data changed, so
   clicks, focus, scroll and the open Model dropdown survive the ~3 redraws a second. */
(function () {
  const esc = s => LS.esc(s);
  const $ = (root, sel) => root.querySelector(sel);

  // Puts html into el only when it differs from last time; returns true when it did.
  function put(el, html) {
    if (el._html === html) return false;
    el._html = html;
    el.innerHTML = html;
    return true;
  }

  // A switch (.sw + .swtxt): click or Space/Enter runs the action, and it flips at once.
  function bindSwitch(sw, actionName) {
    const flip = () => {
      const on = sw.dataset.on !== "1";
      sw.dataset.on = on ? "1" : "0";
      const t = sw.nextElementSibling;
      if (t && t.classList.contains("swtxt") && /^(ON|OFF)$/.test(t.textContent)) t.textContent = on ? "ON" : "OFF";
      LS.act(actionName);
    };
    sw.onclick = flip;
    sw.onkeydown = e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); flip(); } };
  }

  function setSwitch(sw, on, text) {
    sw.dataset.on = on ? "1" : "0";
    const t = sw.nextElementSibling;
    if (t) t.textContent = text ?? (on ? "ON" : "OFF");
  }

  // ---------------------------------------------------------------- Cheat check

  const SUMMARY_KEY = /^([A-Z][A-Za-z ()']*?):(\s|$)/;

  // demo_check.summary_text with the mockup's look: keys bold and in capitals, STRONG in red.
  function summaryHTML(text) {
    return text.split("\n").map(line => {
      const m = SUMMARY_KEY.exec(line);
      if (m && !line.startsWith(" ")) return `<b>${esc(m[1].toUpperCase())}</b>${esc(line.slice(m[1].length + 1))}`;
      return esc(line).replace(/STRONG( \([^)]*\))?/g, s => `<span class="r">${s}</span>`)
                      .replace(/(\d+ detections?)/, s => line.includes("STRONG") ? `<span class="r">${s}</span>` : s);
    }).join("\n");
  }

  // The details JSON with the mockup's colours: keys, strings, numbers.
  function jsonHTML(text) {
    return esc(text).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|((?<!&#)-?\b\d+(?:\.\d+)?\b)/g, (all, str, colon, num) => {
      if (str) return colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`;
      return `<span class="n">${num}</span>`;
    });
  }

  function logHTML(lines) {
    if (!lines.length) return `<span class="lab">Last checks</span><div class="cl">No checks yet.</div>`;
    return `<span class="lab">Last checks</span><div>` + lines.map(line => {
      const parts = line.split(/\s{3,}/);
      const found = parts.findIndex(p => /^found /.test(p));
      return `<div class="cl"><b>${esc(parts[0])}</b>` + parts.slice(1).map((p, i) =>
        ` &middot; ${i + 1 === found ? `<span class="r">${esc(p)}</span>` : esc(p)}`).join("") + `</div>`;
    }).join("") + `</div>`;
  }

  function meaningHTML(entries) {
    return entries.map(e => `<div class="mean">
        <div class="mh"><code>${esc(e.check)}</code><span class="str ${e.strong ? "strong" : "weak"}">${e.strong ? "STRONG" : "WEAK"}</span></div>
        <div class="ma">${esc(e.about)}</div>
        <p>${esc(e.meaning)}</p></div>`).join("");
  }

  let cheatBuilt = false;
  function buildCheat(sec) {
    sec.innerHTML = `
      <div class="ph"><h1>Cheat check</h1><span class="crumb">// demo analysis &middot; local</span></div>
      <div class="pad">
        <div class="row">
          <div class="pnl"><div class="set"><div class="st"><b>Live cheat check</b><span>Checks the demo TF2 records about once a minute, with demo-analysis.</span></div><span class="sw" data-k="check" role="switch" tabindex="0"></span><span class="swtxt"></span></div></div>
          <div class="pnl"><div class="set"><div class="st"><b>Keep only demos with a cheater</b><span>Deletes a finished match's demo if nothing was found.</span></div><span class="sw" data-k="keep" role="switch" tabindex="0"></span><span class="swtxt"></span></div></div>
        </div>
        <div class="row">
          <div class="pnl"><div class="set"><div class="st"><b>Record only with a flagged player</b><span class="rabout"></span></div><span class="sw" data-k="record" role="switch" tabindex="0"></span><span class="swtxt"></span></div></div>
        </div>
        <div class="lastchk"><span class="lab">Cheat check</span><b class="cstate"></b><span class="crec"></span><span class="csp"></span><button class="btn sm" data-a="cheat_check_now">Check now</button></div>
        <div class="chklog"></div>
        <div class="found brk">
          <span class="tag">FOUND</span><span class="who"></span><span class="what"></span>
          <span class="sp"></span>
          <button class="btn dng sm" data-a="cheat_votekick">Votekick</button>
          <button class="btn sm" data-a="cheat_copy">Copy</button>
          <button class="btn sm" data-a="cheat_export" title="A folder next to the demos with the demo, its detections and a report, for the picked player">Export evidence</button>
          <button class="btn sm" data-a="cheat_open">Open&hellip;</button>
          <button class="btn sm ghost" data-a="cheat_open_folder">Open demos folder</button>
        </div>
        <div class="summrow">
          <div class="summ"></div>
          <div class="pnl meanbox"><div class="pnl-h"><span class="lab">What these mean</span></div><div class="means"></div></div>
        </div>
        <div class="cols3">
          <div><div class="pnl-h"><span class="lab">Players</span></div><div class="dplayers"></div></div>
          <div><div class="pnl-h"><span class="lab">Detections</span><span class="num" style="margin-left:auto;font-size:11px;color:var(--tx3)">tick : algorithm</span></div><div class="ddets"></div></div>
          <div><div class="pnl-h"><span class="lab">Details</span></div><div class="ddetails"></div></div>
        </div>
      </div>`;
    sec.querySelectorAll("[data-a]").forEach(b => b.onclick = () => LS.act(b.dataset.a));
    bindSwitch($(sec, '.sw[data-k="check"]'), "cheat_toggle_check");
    bindSwitch($(sec, '.sw[data-k="keep"]'), "cheat_toggle_keep");
    bindSwitch($(sec, '.sw[data-k="record"]'), "cheat_toggle_record");
    const players = $(sec, ".dplayers"), dets = $(sec, ".ddets"), details = $(sec, ".ddetails");
    players.onclick = e => {
      const li = e.target.closest(".li");
      if (!li) return;
      players.querySelectorAll(".li").forEach(x => x.classList.toggle("sel", x === li));
      LS.act("cheat_pick_player", li.dataset.sid);
    };
    players.ondblclick = e => { const li = e.target.closest(".li"); if (li) LS.act("cheat_open_profile", li.dataset.sid); };
    dets.onclick = e => {
      const d = e.target.closest(".det");
      if (!d) return;
      dets.querySelectorAll(".det").forEach(x => x.classList.toggle("sel", x === d));
      LS.act("cheat_pick_det", d.dataset.key);
    };
    details.onclick = e => { if (e.target.closest(".cmdline .btn")) LS.act("cheat_copy_goto"); };
    cheatBuilt = true;
  }

  LS.page("Cheat check", s => {
    const sec = document.getElementById("p-cheat");
    if (!sec || s.error) return;
    if (!cheatBuilt) buildCheat(sec);
    setSwitch($(sec, '.sw[data-k="check"]'), s.check);
    setSwitch($(sec, '.sw[data-k="keep"]'), s.keep);
    setSwitch($(sec, '.sw[data-k="record"]'), s.record_only);
    $(sec, ".rabout").textContent = s.record_about;
    const rec = $(sec, ".crec");
    rec.textContent = s.record;
    rec.classList.toggle("on", s.recording);
    $(sec, ".cstate").textContent = s.state.replace(/^Cheat check: /, "");
    put($(sec, ".chklog"), logHTML(s.log));
    const found = $(sec, ".found");
    found.classList.toggle("none", !s.found);
    $(sec, ".found .tag").textContent = s.found ? "FOUND" : "NOTHING FOUND";
    $(sec, ".found .who").textContent = s.found ? s.found.who : "";
    $(sec, ".found .what").textContent = s.found ? s.found.what : "No player with detections yet.";
    put($(sec, ".summ"), summaryHTML(s.summary));
    put($(sec, ".means"), meaningHTML(s.meaning));
    put($(sec, ".dplayers"), s.players.length ? s.players.map(p =>
      `<div class="li${p.sid === s.picked ? " sel" : ""}" data-sid="${esc(p.sid)}" title="Double-click: Steam profile">` +
      `<span class="mark ${p.strong ? "m-red" : "m-yel"}" style="height:14px"></span><span class="nm">${esc(p.name)}</span>` +
      `<span class="c${p.strong ? " r" : ""}">${p.count}</span></div>`).join("")
      : `<div class="empty">Nothing found yet.</div>`);
    put($(sec, ".ddets"), s.dets.map(d =>
      `<div class="det${d.key === s.det ? " sel" : ""}" data-key="${esc(d.key)}"><span class="t">${d.tick}</span>` +
      `<span class="al">${esc(d.check)}</span><span class="cf ${d.strong ? "strong" : "weak"}">${d.strong ? "STRONG" : "weak"}</span></div>`).join("")
      || `<div class="empty">${s.players.length ? "" : "Click a player, then a detection."}</div>`);
    put($(sec, ".ddetails"), s.details
      ? `<div class="json">${jsonHTML(s.details)}</div>` +
        (s.goto ? `<div class="cmdline"><span>${esc(s.goto)}</span><button class="btn sm">Copy</button></div>` : "")
      : `<div class="empty">Click a player, then a detection.</div>`);
  });

  // ---------------------------------------------------------------- Duels

  const CHEVRON = `<svg viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3"/></svg>`;

  function commandHTML(cmd) {  // "!duel <name>, <name>": the <...> parts dimmed, as on the Help page
    return esc(cmd).replace(/&lt;[^&]*&gt;/g, s => `<em>${s}</em>`);
  }

  function duelHTML(d) {
    if (d.text) return `<div class="dueltxt">${esc(d.text)}</div>`;
    return `<div class="duel">${d.label ? `<span class="dlab lab">${esc(d.label)}</span>` : ""}` +
      `<span class="p ${d.ta}">${esc(d.a)}</span><span class="sc">${esc(d.sa)}<em>-</em>${esc(d.sb)}</span>` +
      `<span class="p ${d.tb} rt">${esc(d.b)}</span></div>`;
  }

  let duelsBuilt = false;
  function buildDuels(sec) {
    sec.innerHTML = `
      <div class="ph"><h1>Duels</h1><span class="crumb"></span></div>
      <div class="pad">
        <div class="bigsw brk"><span class="sw" role="switch" tabindex="0"></span><span class="swtxt"></span><div><b class="dtitle"></b><span class="dabout"></span></div></div>
        <div class="row">
          <div class="pnl" style="flex:1.3">
            <div class="pnl-h"><span class="lab">Running now</span><span class="num dcount" style="font-size:11px;color:var(--tx3)"></span><span style="margin-left:auto"></span><button class="btn dng sm" data-a="duels_stop">Stop all duels</button></div>
            <div class="dlist"></div>
          </div>
          <div class="pnl hv dmodel">
            <div class="pnl-h"><span class="lab">Model</span></div>
            <div class="pnl-b">
              <div class="model"><span class="mname"></span><span class="q"></span>${CHEVRON}<select class="msel" title="The one asked first. Click to pick another."></select></div>
              <div class="mmeter"></div>
            </div>
          </div>
        </div>
        <div class="pnl hv">
          <div class="pnl-h"><span class="lab">Who can mute Heavy</span></div>
          <div class="pnl-b" style="display:flex;gap:16px;align-items:center">
            <div class="seg" style="width:420px"><button data-lock="off">Anyone</button><button data-lock="on">Stays on</button><button data-lock="muted">Stays muted</button></div>
            <span style="color:var(--tx3);font-size:12px">Do !badbot and !goodbot work for others?</span>
          </div>
        </div>
        <div class="pnl hv">
          <div class="pnl-h"><span class="lab">Tokens today</span><span style="margin-left:auto"></span><button class="btn sm dtokwin" data-a="duels_token_window"></button></div>
          <div class="dtokens"></div>
        </div>
        <div class="pnl hc">
          <div class="pnl-h"><span class="lab">What players can type in chat</span></div>
          <div class="pnl-b dcmds"></div>
        </div>
      </div>`;
    sec.querySelectorAll("[data-a]").forEach(b => b.onclick = () => LS.act(b.dataset.a));
    bindSwitch($(sec, ".bigsw .sw"), "duels_toggle");
    sec.querySelectorAll(".seg button").forEach(b => b.onclick = () => {
      sec.querySelectorAll(".seg button").forEach(x => x.classList.toggle("on", x === b));
      LS.act("duels_lock", b.dataset.lock);
    });
    const sel = $(sec, ".msel");
    sel.onchange = () => { LS.act("duels_model", sel.value); sel.blur(); };
    duelsBuilt = true;
  }

  LS.page("Duels", s => {
    const sec = document.getElementById("p-duels");
    if (!sec || s.error) return;
    if (!duelsBuilt) buildDuels(sec);
    $(sec, ".crumb").textContent = s.heavy ? "// HoovyGPT + 1v1 scoring from chat" : "// 1v1 scoring from chat";
    setSwitch($(sec, ".bigsw .sw"), s.on, s.text);
    $(sec, ".bigsw .swtxt").classList.toggle("wide", s.text.length > 3);
    $(sec, ".dtitle").textContent = s.title;
    $(sec, ".dabout").textContent = s.about;
    $(sec, ".dcount").textContent = s.duels.length ? `${s.duels.length} duel${s.duels.length === 1 ? "" : "s"}` : "";
    put($(sec, ".dlist"), s.duels.length ? s.duels.map(duelHTML).join("") : `<div class="dueltxt muted">No duels running.</div>`);
    put($(sec, ".dcmds"), s.commands.map(([c, about]) => `<div class="cmd"><code>${commandHTML(c)}</code><span>${esc(about)}</span></div>`).join(""));
    sec.querySelectorAll(".hv").forEach(el => el.style.display = s.heavy ? "" : "none");
    if (!s.heavy) return;
    const m = s.model;
    $(sec, ".mname").textContent = m.name;
    $(sec, ".q").textContent = m.label;
    const sel = $(sec, ".msel");
    if (document.activeElement !== sel) {
      const opts = m.choices.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
      put(sel, opts);
      sel.value = m.value;
    }
    put($(sec, ".mmeter"), m.limit && m.left !== null
      ? `<div class="meter"><i style="width:${Math.max(0, Math.min(100, m.left / m.limit * 100))}%"></i></div>` +
        `<div class="num" style="font-size:11px;color:var(--tx3);margin-top:6px">${m.left} / ${m.limit} free answers left today</div>`
      : `<div class="num" style="font-size:11px;color:var(--tx3)">The one asked first. Click to pick another.</div>`);
    sec.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.lock === s.lock));
    $(sec, ".dtokwin").textContent = s.token_window ? "Close the tokens window" : "Open in its own window";
    const t = s.tokens;
    put($(sec, ".dtokens"), `<table class="dt"><thead><tr>${t.columns.map((c, i) =>
        `<th${i ? ' class="r"' : ""}>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
      t.rows.map(([first, ...cells]) => `<tr${first ? ' class="first"' : ""}>` + cells.map((c, i) =>
        `<td${i ? ' class="r"' : ""}>${esc(c)}</td>`).join("") + `</tr>`).join("") +
      `</tbody></table><div class="tnote num">${esc(t.note)}</div>`);
  });
})();

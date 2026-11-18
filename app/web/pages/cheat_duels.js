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

  // Numbers in a plain text in the code font (the visual pass: the code font only for numbers).
  // Not the digits of an escaped character (&#39;) or inside a word (a name like "Player2").
  function numHTML(text) {
    return esc(text).replace(/(?<!&#)\b\d+(?:[.:]\d+)*\b/g, n => `<span class="num">${n}</span>`);
  }

  // Thin outline icons, the sidebar's style (16x16, stroke only).
  const ICON = {
    kick: `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="6" cy="5" r="2.5"/><path d="M1.5 14c0-2.8 2-4.5 4.5-4.5s4.5 1.7 4.5 4.5"/><path d="M11 6.5h4"/></svg>`,
    export: `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 10V2M5 5l3-3 3 3"/><path d="M3 8.5V14h10V8.5"/></svg>`,
    chevron: `<svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3"/></svg>`,
  };

  function setSwitch(sw, on, text) {
    sw.dataset.on = on ? "1" : "0";
    const t = sw.nextElementSibling;
    if (t) t.textContent = text ?? (on ? "ON" : "OFF");
  }

  // ---------------------------------------------------------------- Cheat check

  // The details JSON with the mockup's colours: keys, strings, numbers.
  function jsonHTML(text) {
    return esc(text).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|((?<!&#)-?\b\d+(?:\.\d+)?\b)/g, (all, str, colon, num) => {
      if (str) return colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`;
      return `<span class="n">${num}</span>`;
    });
  }

  // One check of the log: time, how much was read, what was found; the demo only when it isn't the table's.
  function checkHTML(e) {
    return `<b class="num">${esc(e.time)}</b>` + (e.demo ? ` &middot; ${esc(e.demo)}` : "") + (e.read ? ` &middot; ${numHTML(e.read)}` : "") +
      (e.found ? ` &middot; <span class="${/^found /.test(e.found) ? "f" : ""}">${numHTML(e.found)}</span>` : "") +
      (e.after ? ` &middot; ${esc(e.after)}` : "");
  }

  function lastHTML(log) {
    if (!log.length) return `<span class="lab">Last check</span><span>none yet</span>`;
    return `<span class="lab">Last check</span><span class="cl">${checkHTML(log[0])}</span>`;
  }

  // The checked demo: map, length and file on one line, then one row per player and check.
  function tableHTML(t) {
    if (!t) return `<div class="pnl-h"><span class="lab">Found in the demo</span></div><div class="empty">Nothing found yet.</div>`;
    const head = `<div class="pnl-h"><span class="lab">Found in the demo</span>` +
      `<span class="dmeta">${esc(t.map)} &middot; <span class="num">${esc(t.duration)}</span> &middot; ${esc(t.file)}</span></div>`;
    if (!t.rows.length) return head + `<div class="empty">Nothing found in this demo.</div>`;
    let last = null;
    return head + `<table class="dt ftab"><thead><tr><th>Player</th><th>What was found</th><th class="r">Times</th><th class="r">Strength</th></tr></thead><tbody>` +
      t.rows.map(r => {
        const first = r.sid !== last;
        last = r.sid;
        return `<tr class="${first ? "pfirst" : "pmore"}"><td>${first ? esc(r.name) + (r.you ? ` <span class="you">(you)</span>` : "") : ""}</td>` +
          `<td><span class="about">${esc(r.about)}</span><span class="ck">${esc(r.check)}</span></td>` +
          `<td class="r num">${r.count}</td>` +
          `<td class="r"><span class="str ${r.strong ? "strong" : "weak"}">${r.strong ? "STRONG" : "weak"}</span></td></tr>`;
      }).join("") + `</tbody></table>`;
  }

  function meaningHTML(entries) {
    return entries.map(e => `<div class="mean">
        <div class="mh"><span class="ck">${esc(e.check)}</span><span class="str ${e.strong ? "strong" : "weak"}">${e.strong ? "STRONG" : "WEAK"}</span></div>
        <div class="ma">${esc(e.about)}</div>
        <p>${esc(e.meaning)}</p></div>`).join("");
  }

  // The Export menu: what the FOUND bar's other four buttons did. Each named by what it does.
  const EXPORTS = [
    ["cheat_copy", "Copy chat lines", "Copies one line per player, each fits a TF2 chat message"],
    ["cheat_export", "Save evidence file", "A folder next to the demos with the demo, its detections and a report, for the picked player"],
    ["cheat_open", "Open demo", "Show a saved cheat check result (from this or an earlier match)"],
    ["cheat_open_folder", "Open demos folder", "Open TF2's demos folder"],
  ];

  let cheatBuilt = false;
  function buildCheat(sec) {
    sec.innerHTML = `
      <div class="ph"><h1>Cheat check</h1><span class="crumb">// demo analysis &middot; local</span></div>
      <div class="pad">
        <div class="row">
          <div class="pnl"><div class="set"><div class="st"><b>Demo check</b><span>Checks the demo TF2 records about once a minute, with demo-analysis.</span></div><span class="sw" data-k="check" role="switch" tabindex="0"></span><span class="swtxt"></span></div></div>
          <div class="pnl"><div class="set"><div class="st"><b>Keep only demos with a cheater</b><span>Deletes a finished match's demo if nothing was found.</span></div><span class="sw" data-k="keep" role="switch" tabindex="0"></span><span class="swtxt"></span></div></div>
        </div>
        <div class="row">
          <div class="pnl"><div class="set"><div class="st"><b>Record only with a flagged player</b><span class="rabout"></span></div><span class="sw" data-k="record" role="switch" tabindex="0"></span><span class="swtxt"></span></div></div>
        </div>
        <div class="lastchk">
          <span class="cstate"></span><span class="crec"></span><span class="clast"></span>
          <button class="btn sm ghost cmore" aria-expanded="false"></button>
          <span class="csp"></span><button class="btn sm" data-a="cheat_check_now">Check now</button>
        </div>
        <div class="chklog"></div>
        <div class="found brk">
          <span class="tag">FOUND</span><span class="who"></span><span class="what"></span>
          <span class="sp"></span>
          <div class="fbtns">
          <button class="btn sm kick" data-a="cheat_votekick">${ICON.kick}Votekick</button>
          <div class="xport">
            <button class="btn sm xbtn" aria-haspopup="menu" aria-expanded="false">${ICON.export}Export${ICON.chevron}</button>
            <div class="xmenu" role="menu" hidden>${EXPORTS.map(([a, label, about]) =>
              `<button role="menuitem" data-x="${a}" title="${esc(about)}">${esc(label)}</button>`).join("")}</div>
          </div>
          </div>
        </div>
        <div class="summrow">
          <div class="pnl ftable"></div>
          <div class="pnl meanbox"><div class="pnl-h"><span class="lab">What these mean</span></div><div class="means"></div></div>
        </div>
        <div class="cols3">
          <div><div class="pnl-h"><span class="lab">Players</span></div><div class="dplayers"></div></div>
          <div><div class="pnl-h"><span class="lab">Detections</span><span class="dhint">tick : check</span></div><div class="ddets"></div></div>
          <div><div class="pnl-h"><span class="lab">Details</span></div><div class="ddetails"></div></div>
        </div>
      </div>`;
    sec.querySelectorAll("[data-a]").forEach(b => b.onclick = () => LS.act(b.dataset.a));
    bindSwitch($(sec, '.sw[data-k="check"]'), "cheat_toggle_check");
    bindSwitch($(sec, '.sw[data-k="keep"]'), "cheat_toggle_keep");
    bindSwitch($(sec, '.sw[data-k="record"]'), "cheat_toggle_record");
    // Export menu: opens under its button, closes on a pick, a click elsewhere or Escape.
    const xbtn = $(sec, ".xbtn"), xmenu = $(sec, ".xmenu");
    const openMenu = open => { xmenu.hidden = !open; xbtn.setAttribute("aria-expanded", open ? "true" : "false"); };
    xbtn.onclick = e => { e.stopPropagation(); openMenu(xmenu.hidden); };
    xmenu.onclick = e => {
      const item = e.target.closest("[data-x]");
      if (!item) return;
      openMenu(false);
      LS.act(item.dataset.x);
    };
    document.addEventListener("click", e => { if (!e.target.closest(".xport")) openMenu(false); });
    document.addEventListener("keydown", e => { if (e.key === "Escape") openMenu(false); });
    // The earlier checks: behind "+N earlier".
    const more = $(sec, ".cmore"), log = $(sec, ".chklog");
    log.hidden = true;
    more.onclick = () => {
      log.hidden = !log.hidden;
      more.textContent = log.hidden ? `Show ${more.dataset.n} earlier` : "Hide earlier";
      more.setAttribute("aria-expanded", log.hidden ? "false" : "true");
    };
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
    // The status line: only what the switches above don't already say.
    const st = $(sec, ".cstate");
    st.textContent = s.state;
    st.hidden = !s.state;
    const rec = $(sec, ".crec");
    rec.hidden = !s.recording;
    if (s.recording) {
      rec.textContent = s.recording.text;
      rec.classList.toggle("on", s.recording.on);
    }
    put($(sec, ".clast"), lastHTML(s.log));
    const more = $(sec, ".cmore"), log = $(sec, ".chklog");
    more.dataset.n = s.log.length - 1;
    more.hidden = s.log.length < 2;
    if (more.hidden) log.hidden = true;
    more.textContent = log.hidden ? `Show ${more.dataset.n} earlier` : "Hide earlier";
    put(log, s.log.slice(1).map(e => `<div class="cl">${checkHTML(e)}</div>`).join(""));
    const found = $(sec, ".found");
    found.classList.toggle("none", !s.found);
    found.classList.toggle("strong", !!(s.found && s.found.strong));  // red only for a STRONG find
    $(sec, ".found .tag").textContent = s.found ? "FOUND" : "NOTHING FOUND";
    $(sec, ".found .who").textContent = s.found ? s.found.who : "";
    put($(sec, ".found .what"), s.found ? numHTML(s.found.what) : "No player with detections yet.");
    // Votekick: greyed with the reason in its hover when the vote can't work (a click still says why).
    const kick = $(sec, ".kick");
    kick.classList.toggle("no", !s.kick.ok);
    kick.setAttribute("aria-disabled", s.kick.ok ? "false" : "true");
    kick.title = s.kick.why;
    put($(sec, ".ftable"), tableHTML(s.table));
    put($(sec, ".means"), meaningHTML(s.meaning));
    put($(sec, ".dplayers"), s.players.length ? s.players.map(p =>
      `<div class="li${p.sid === s.picked ? " sel" : ""}" data-sid="${esc(p.sid)}" title="Double-click: Steam profile">` +
      `<span class="mark ${p.strong ? "m-red" : "m-yel"}" style="height:14px"></span><span class="nm">${esc(p.name)}</span>` +
      `<span class="c num${p.strong ? " r" : ""}">${p.count}</span></div>`).join("")
      : `<div class="empty">Nothing found yet.</div>`);
    put($(sec, ".ddets"), s.dets.map(d =>
      `<div class="det${d.key === s.det ? " sel" : ""}" data-key="${esc(d.key)}"><span class="t">${d.tick}</span>` +
      `<span class="al">${esc(d.check)}</span><span class="cf ${d.strong ? "strong" : "weak"}">${d.strong ? "STRONG" : "weak"}</span></div>`).join("")
      || `<div class="empty">${s.players.length ? "" : "Click a player, then a detection."}</div>`);
    put($(sec, ".ddetails"), s.details
      ? `<div class="json">${jsonHTML(s.details)}</div>` +
        (s.goto ? `<div class="cmdline"><span>${esc(s.goto)}</span><button class="btn sm" title="Copies this TF2 console command">Copy command</button></div>` : "")
      : `<div class="empty">Click a player, then a detection.</div>`);
  });

  // ---------------------------------------------------------------- Duels

  const CHEVRON = ICON.chevron;

  function commandHTML(cmd) {  // "!duel <name>, <name>": the <...> parts dimmed, as on the Help page
    return esc(cmd).replace(/&lt;[^&]*&gt;/g, s => `<em>${s}</em>`);
  }

  function duelHTML(d) {
    if (d.text) return `<div class="dueltxt">${esc(d.text)}</div>`;
    return `<div class="duel">${d.label ? `<span class="dlab lab">${esc(d.label)}</span>` : ""}` +
      `<span class="p ${d.ta}">${esc(d.a)}</span><span class="sc num">${esc(d.sa)}<em>-</em>${esc(d.sb)}</span>` +
      `<span class="p ${d.tb} rt">${esc(d.b)}</span></div>`;
  }

  let duelsBuilt = false;
  function buildDuels(sec) {
    sec.innerHTML = `
      <div class="ph"><h1>HoovyGPT</h1><span class="crumb">// AI chat bot + duels</span></div>
      <div class="pad">
        <div class="bigsw brk"><span class="sw" role="switch" tabindex="0"></span><span class="swtxt"></span><div><b class="dtitle"></b><span class="dabout"></span></div></div>
        <div class="row">
          <div class="pnl" style="flex:1.3">
            <div class="pnl-h"><span class="lab">Running now</span><span class="dcount"></span><span style="margin-left:auto"></span><button class="btn sm ghost dstop" data-a="duels_stop">Stop all duels</button></div>
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
          <div class="pnl-h"><span class="lab dlockq"></span></div>
          <div class="pnl-b dlock">
            <div class="seg"></div>
            <span class="dlockhint"></span>
          </div>
        </div>
        <div class="pnl hv dtokpnl">
          <div class="pnl-h"><span class="lab">Tokens today</span><span style="margin-left:auto"></span><button class="btn sm ghost dtokbtn" aria-expanded="false">Show details</button></div>
          <div class="dtokens" hidden></div>
        </div>
        <div class="pnl hc">
          <div class="pnl-h"><span class="lab">What players can type in chat</span></div>
          <div class="pnl-b dcmds"></div>
        </div>
      </div>`;
    sec.querySelectorAll("[data-a]").forEach(b => b.onclick = () => LS.act(b.dataset.a));
    bindSwitch($(sec, ".bigsw .sw"), "duels_toggle");
    // The !badbot choice: its buttons come from the state (named by what each does).
    $(sec, ".seg").onclick = e => {
      const b = e.target.closest("button[data-lock]");
      if (!b) return;
      sec.querySelectorAll(".seg button").forEach(x => x.classList.toggle("on", x === b));
      $(sec, ".dlockhint").textContent = b.title;
      LS.act("duels_lock", b.dataset.lock);
    };
    // Tokens today: closed by default, its table only behind Details.
    const tokbtn = $(sec, ".dtokbtn"), tokens = $(sec, ".dtokens");
    tokbtn.onclick = () => {
      tokens.hidden = !tokens.hidden;
      tokbtn.setAttribute("aria-expanded", tokens.hidden ? "false" : "true");
      tokbtn.textContent = tokens.hidden ? "Show details" : "Hide details";
      $(sec, ".dtokpnl").classList.toggle("shut", tokens.hidden);
    };
    $(sec, ".dtokpnl").classList.add("shut");
    const sel = $(sec, ".msel");
    sel.onchange = () => { LS.act("duels_model", sel.value); sel.blur(); };
    duelsBuilt = true;
  }

  LS.page("Duels", s => {
    const sec = document.getElementById("p-duels");
    if (!sec || s.error) return;
    if (!duelsBuilt) buildDuels(sec);
    setSwitch($(sec, ".bigsw .sw"), s.on, s.text);
    $(sec, ".bigsw .swtxt").classList.toggle("wide", s.text.length > 3);
    $(sec, ".dtitle").textContent = s.title;
    $(sec, ".dabout").textContent = s.about;
    $(sec, ".dcount").textContent = s.duels.length ? `${s.duels.length} duel${s.duels.length === 1 ? "" : "s"}` : "";
    // Stop all duels posts in chat: its hover shows the exact lines first.
    $(sec, ".dstop").title = s.stop_preview.length ? "Posts in chat:\n" + s.stop_preview.join("\n") : "No duels running";
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
        `<div class="mnote">${numHTML(`${m.left} / ${m.limit} free answers left today`)}</div>`
      : `<div class="mnote">The one asked first. Click to pick another.</div>`);
    $(sec, ".dlockq").textContent = s.lock_question;
    put($(sec, ".seg"), s.lock_options.map(([v, label, effect]) =>
      `<button data-lock="${esc(v)}" title="${esc(effect)}">${esc(label)}</button>`).join(""));
    sec.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.lock === s.lock));
    const picked = s.lock_options.find(o => o[0] === s.lock);
    $(sec, ".dlockhint").textContent = picked ? picked[2] : "";
    const t = s.tokens;
    put($(sec, ".dtokens"), `<table class="dt"><thead><tr>${t.columns.map((c, i) =>
        `<th${i ? ' class="r"' : ""}>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
      t.rows.map(([first, ...cells]) => `<tr${first ? ' class="first"' : ""}>` + cells.map((c, i) =>
        `<td${i ? ' class="r"' : ""}>${esc(c)}</td>`).join("") + `</tr>`).join("") +
      `</tbody></table><div class="tnote">${esc(t.note)}</div>`);
  });
})();

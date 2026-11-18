/* Page script: the Players page (state from web_players.py). The toolbar is built once; the
   teams, the chips, the Columns menu and the selected player's panel are each replaced only when
   their HTML changed, so the search box keeps focus and the list keeps its scroll. */
(function () {
  const esc = s => LS.esc(s);
  const act = (...a) => LS.act(...a);
  const WIDTH = {Mark: 22, Ctry: 46, Class: 128, HP: 190, "K/D": 76, Streak: 96, Duel: 66, HS: 108,
                 Crit: 108, TF2: 86, Age: 74, Flags: 270, Profile: 200};
  let built = false, menuOpen = false;
  const last = {};
  // "Likely together" guesses: a small G1/G2 chip per group (its colour by number), and one
  // tooltip shared by every (Why?) and chip, placed in the window so the edge never cuts it.
  let why = "", tip = null, tipOn = null, mouse = [0, 0];
  const WHY = `<span class="pl-why" tabindex="0">(Why?)</span>`;
  const chip = n => `<span class="pl-grp g${(n - 1) % 6}">G${n}</span>`;

  function showTip(anchor) {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "pl-tip";
      tip.setAttribute("role", "tooltip");
      document.body.appendChild(tip);
    }
    tipOn = anchor;
    tip.textContent = why;
    tip.style.display = "block";
    const r = anchor.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight, pad = 8;
    const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
    let x = Math.min(Math.max(pad, r.left + r.width / 2 - w / 2), vw - w - pad);
    let y = r.bottom + 6;
    if (y + h > vh - pad) y = Math.max(pad, r.top - h - 6);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }

  function hideTip() {
    tipOn = null;
    if (tip) tip.style.display = "none";
  }

  // After a re-render the hovered (Why?) may have been replaced: follow the mouse to its new copy.
  function refreshTip() {
    if (!tipOn || tipOn.isConnected) return;
    const el = document.elementFromPoint(mouse[0], mouse[1]);
    const a = el && el.closest(".pl-why,.pl-grp");
    a ? showTip(a) : hideTip();
  }

  function set(el, key, html) {
    if (last[key] === html) return false;
    last[key] = html;
    el.innerHTML = html;
    return true;
  }

  function build(sec) {
    sec.innerHTML = `
      <div class="toolbar">
        <div class="chips" id="pl-chips"></div>
        <label class="search"><svg viewBox="0 0 14 14"><circle cx="6" cy="6" r="4.3"/><path d="M9.3 9.3L13 13"/></svg><input id="pl-q" placeholder="Search name" aria-label="Search players" spellcheck="false" autocomplete="off"></label>
        <span class="pl-colwrap">
          <button class="btn" id="pl-colbtn"><svg viewBox="0 0 14 14"><rect x="1.5" y="2" width="11" height="10"/><path d="M5.3 2v10M8.7 2v10"/></svg>Columns</button>
          <div class="pl-colmenu" id="pl-colmenu" hidden></div>
        </span>
        <span class="grow"></span>
        <div class="saygrp">
          <span class="lab">Say in chat</span>
          <button class="btn sm" data-lobby="summary">Lobby summary</button>
          <button class="btn sm" data-lobby="kill_race">Kill race</button>
        </div>
      </div>
      <div class="pgrid" id="pl-grid">
        <div class="teams" id="pl-teams"></div>
        <aside class="detail" id="pl-detail"></aside>
      </div>`;
    const q = sec.querySelector("#pl-q");
    q.addEventListener("input", () => act("players_search", q.value));
    q.addEventListener("keydown", e => {
      if (e.key === "Escape") { q.value = ""; act("players_search", ""); }
      if (e.key === "Enter") q.blur();
    });
    sec.querySelector("#pl-chips").addEventListener("click", e => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      sec.querySelectorAll("#pl-chips .chip").forEach(c => c.classList.toggle("on", c === chip));
      act("players_filter", chip.dataset.f);
    });
    const menu = sec.querySelector("#pl-colmenu");
    sec.querySelector("#pl-colbtn").addEventListener("click", e => {
      e.stopPropagation();
      menuOpen = !menuOpen;
      menu.hidden = !menuOpen;
    });
    menu.addEventListener("click", e => {
      e.stopPropagation();
      const row = e.target.closest("[data-col]");
      if (!row) return;
      row.classList.toggle("on");
      act("players_column", row.dataset.col);
    });
    document.addEventListener("click", () => { if (menuOpen) { menuOpen = false; menu.hidden = true; } });
    sec.addEventListener("mouseover", e => {
      const a = e.target.closest(".pl-why,.pl-grp");
      if (a && a !== tipOn) showTip(a);
    });
    sec.addEventListener("mouseout", e => {
      const a = e.target.closest(".pl-why,.pl-grp");
      if (a && a === tipOn && !a.contains(e.relatedTarget)) hideTip();
    });
    sec.addEventListener("focusin", e => { if (e.target.matches(".pl-why")) showTip(e.target); });
    sec.addEventListener("focusout", e => { if (e.target === tipOn) hideTip(); });
    document.addEventListener("mousemove", e => { mouse = [e.clientX, e.clientY]; }, {passive: true});
    sec.querySelectorAll("[data-lobby]").forEach(b => b.addEventListener("click", () => act("players_lobby", b.dataset.lobby)));
    sec.querySelector("#pl-teams").addEventListener("click", e => {
      const th = e.target.closest("th[data-sort]");
      if (th) { act("players_sort", th.dataset.sort); return; }
      const tr = e.target.closest("tr[data-sid]");
      if (!tr) return;
      const was = tr.classList.contains("sel");
      sec.querySelectorAll("#pl-teams tr.sel").forEach(r => r.classList.remove("sel"));
      if (!was) tr.classList.add("sel");
      act("players_select", tr.dataset.sid);
    });
    sec.querySelector("#pl-detail").addEventListener("click", e => {
      const b = e.target.closest("button");
      if (!b || b.disabled) return;
      if (b.dataset.close !== undefined) act("players_deselect");
      else if (b.dataset.act) act("players_act", b.dataset.act);
    });
    built = true;
  }

  // --- the list ------------------------------------------------------------------------------

  function cell(column, c) {
    switch (column) {
      case "Mark":
        return `<span class="mark m-${c.m}" title="${esc(c.title)}"></span>`;
      case "Ctry":
        return c.img ? `<img class="pl-flag" src="${c.img}" alt="${esc(c.t)}" title="${esc(c.t)}">`
                     : `<span class="pl-oc" style="color:${c.c}">${esc(c.t)}</span>`;
      case "Class":
        if (!c.t) return "";
        return `<span class="cls">${c.img ? `<img class="pl-ci" src="${c.img}" alt="">` : ""}<span>${esc(c.t)}</span></span>`;
      case "Player":
        return `<span class="pn ${c.you ? "you" : ""}">${esc(c.t)}${c.you ? "<small>(you)</small>" : ""}</span>`;
      case "HP":
        if (c.pct === undefined) return c.t ? `<div class="hp"><span class="v" style="color:${c.c}">${esc(c.t)}</span></div>` : "";
        return `<div class="hp"><span class="v" style="color:${c.c}">${esc(c.t)}</span>` +
               `<span class="bar"><i style="width:${c.pct}%;background:${c.c}"></i></span>` +
               `<span class="mx">${c.max ? "/" + c.max : ""}</span></div>`;
      case "K/D":
        return c.k === undefined ? "" :
          `<span class="kd"><span class="k">${esc(c.k)}</span><span class="s">/</span><span class="d">${esc(c.d)}</span></span>`;
      case "Flags":
        if (!c.t) return `<span class="noflag">&mdash;</span>`;
        return `${c.tag ? `<span class="pl-stamp" style="color:${c.tag[1]}">${esc(c.tag[0])}</span>` : ""}` +
               `<span class="pl-ftx" style="color:${c.c}" title="${esc(c.t)}">${esc(c.t)}</span>`;
      default:
        return `<span class="pl-oc" style="color:${c.c}" title="${esc(c.t)}">${esc(c.t)}</span>`;
    }
  }

  function teamHTML(t, s) {
    const all = s.all_columns, idx = s.shown.map(c => all.indexOf(c));
    const kind = t.colour === "BLU" ? "blu" : t.colour === "RED" ? "red" : "unk";
    const name = t.name.charAt(0) + t.name.slice(1).toLowerCase();
    const head = s.shown.map(c => {
      const w = WIDTH[c] ? ` style="width:${WIDTH[c]}px"` : "";
      const arrow = s.sort && s.sort[0] === c ? (s.sort[1] ? " ▼" : " ▲") : "";
      return `<th${w} data-sort="${esc(c)}" class="${arrow ? "srt" : ""}">${esc(s.headers[c])}${arrow}</th>`;
    }).join("");
    const rows = t.rows.map(r => {
      if (r.sub) return `<tr class="pl-sub"><td colspan="${s.shown.length}">${esc(r.sub)}</td></tr>`;
      return `<tr data-sid="${r.sid}" class="${r.sel ? "sel" : ""}">` + idx.map((i, n) => {
        const c = s.shown[n];
        const grp = c === "Player" && r.grp ? chip(r.grp) : "";
        return `<td${c === "Mark" ? ' style="padding-right:0"' : ""}>${cell(c, r.cells[i])}${grp}</td>`;
      }).join("") + "</tr>";
    }).join("");
    const lineup = t.lineup.map(([n, what]) => `<span class="lu">${n ? `<b>${esc(n)}</b> ` : ""}${esc(what)}</span>`).join("");
    return `<div class="team ${kind}">
      <div class="thead">
        <span class="tname">${esc(name)}${t.colour ? ` &middot; <em>${esc(t.colour)}</em>` : ""}</span>
        <span class="tmeta">${t.count} player${t.count === 1 ? "" : "s"} &middot; <span class="fl ${t.flagged > 1 ? "hi" : ""}">${t.flagged} flagged</span>` +
          `${t.groups ? ` &middot; <span class="pl-gc">${t.groups} likely group${t.groups === 1 ? "" : "s"} ${WHY}</span>` : ""}</span>
        <span class="lineup">${lineup}</span>
      </div>
      <table class="pt"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function legend(s) {
    const sev = s.severity_colours, hp = s.hp_colours;
    return `<div class="legend"><span>MARK</span><span><i style="background:${sev[3]}"></i>cheater</span>` +
      `<span><i style="background:${sev[2]}"></i>suspicious</span><span><i style="background:${sev[1]}"></i>weak flag</span>` +
      `<span style="margin-left:12px">HP</span><span><i style="background:${hp.high}"></i>&ge;66%</span>` +
      `<span><i style="background:${hp.mid}"></i>33-66%</span><span><i style="background:${hp.low}"></i>&lt;33%</span>` +
      `<span><i style="background:${hp.over}"></i>overheal</span></div>`;
  }

  // --- the selected player -------------------------------------------------------------------

  function detailHTML(p) {
    const v = p.verdict
      ? `<span class="verdict" style="background:var(--${p.mark});color:#140505">${esc(p.verdict)}</span>`
      : `<span class="verdict" style="border:1px solid var(--ln2);color:var(--tx3)">CLEAN</span>`;
    const reasons = p.reasons.map(r =>
      `<div class="reason"><span class="str ${r.cls}">${esc(r.level)}</span><p>${esc(r.text)}${r.why ? `<small>${esc(r.why)}</small>` : ""}</p></div>`).join("")
      || `<div style="color:var(--tx3);font-size:12.5px">No flags.</div>`;
    const [acts, says] = p.actions;
    const actBtn = ([key, text, on]) =>
      `<button class="btn${key === "kick" ? " dng" : key === "history" ? " pl-link" : ""}" data-act="${key}"${on ? "" : " disabled"}>${esc(text)}</button>`;
    const sayBtn = ([key, text, on]) => `<button data-act="${key}"${on ? "" : " disabled"}>${esc(text)}</button>`;
    return `
     <div class="dh">${v}
       <span class="lab">Selected player<button class="pl-close" data-close title="Close">&#x2715;</button></span>
       <div class="dname">${esc(p.name)}</div>
       <div class="dsub"><span class="side-t ${p.enemy ? "" : "blu"}">${esc(p.side)}</span>${p.cls ? `<span class="sep">&middot;</span><span>${esc(p.cls)}</span>` : ""}</div>
       ${p.about ? `<div class="pl-about">${esc(p.about)}</div>` : ""}
       ${p.together ? `<div class="pl-tog">${chip(p.together.n)}<span>Likely together with: ${esc(p.together.names.join(", "))}</span> ${WHY}</div>` : ""}
       ${p.you ? `<div class="dmeet">This is you</div>` : ""}
     </div>
     <div class="dstats"><div><b>${esc(p.kd || "-")}</b><span>K/D</span></div><div><b>${esc(p.ratio || "-")}</b><span>Ratio</span></div>` +
     `<div><b style="color:${p.hp ? p.hp_c : "var(--tx3)"}">${esc(p.hp || "-")}</b><span>HP</span></div></div>
     <div class="dsec"><span class="lab">Why flagged</span>${reasons}</div>
     <div class="dsec"><span class="lab">Actions</span><div class="agrid">${acts.map(actBtn).join("")}</div></div>
     <div class="dsec" style="border-bottom:0"><span class="lab">Say in chat</span><div class="sgrid">${says.map(sayBtn).join("")}</div></div>`;
  }

  // --- each render ---------------------------------------------------------------------------

  LS.page("Players", function (s) {
    const sec = document.getElementById("p-players");
    if (!sec || s.error) return;
    if (!built) build(sec);
    why = s.together_why || "";
    set(sec.querySelector("#pl-chips"), "chips", s.filters.map(f =>
      `<button class="chip ${f.key === s.filter ? "on" : ""}" data-f="${f.key}">${esc(f.text)}` +
      `${f.n ? ` <span class="n ${f.key === "cheaters" ? "r" : ""}">${f.n}</span>` : ""}</button>`).join(""));
    const q = sec.querySelector("#pl-q");
    if (document.activeElement !== q && q.value.trim().toLowerCase() !== s.search) q.value = s.search;
    set(sec.querySelector("#pl-colmenu"), "cols", s.columns.map(c =>
      `<button class="${c.on ? "on" : ""}" data-col="${esc(c.key)}"><span class="ck"></span>${esc(c.name)}</button>`).join(""));
    set(sec.querySelector("#pl-teams"), "teams",
      s.empty ? `<div class="empty">${esc(s.empty)}</div>` : s.teams.map(t => teamHTML(t, s)).join("") + legend(s));
    const grid = sec.querySelector("#pl-grid"), detail = sec.querySelector("#pl-detail");
    grid.classList.toggle("pl-nopanel", !s.panel);
    if (s.panel) {
      detail.style.setProperty("--dtc", s.panel.enemy ? "var(--red-d)" : "var(--blu-d)");
      set(detail, "detail", detailHTML(s.panel));
    } else set(detail, "detail", "");
    refreshTip();
  });
})();

/* Page script: the Players page (state from web_players.py). The toolbar is built once; the
   teams, the chips, the menus and the selected player's card are each replaced only when their
   HTML changed, so the search box keeps focus and the list keeps its scroll. */
(function () {
  const esc = s => LS.esc(s);
  const act = (...a) => LS.act(...a);
  const WIDTH = {Mark: 24, Ctry: 48, Class: 120, HP: 184, "K/D": 72, Streak: 96, Duel: 64, HS: 104,
                 Crit: 104, TF2: 80, Age: 72, Flags: 136, Profile: 192};
  // FLAGS holds only the one stamp, so PLAYER takes what is left; a name too long for it ends in
  // "…" (the full name on hover).
  const widthOf = c => (c === "Player" ? 0 : WIDTH[c] || 0);
  const PLAYER_MIN = 160;  // the table never gets narrower than its columns plus this for names
  let built = false, menu = null;  // menu: the open toolbar menu ("col" / "say"), or null
  const last = {};
  // One tooltip box for everything on the page, placed in the window so the edge never cuts it:
  // a player's row or the card's band show how the cheater score adds up, clue by clue
  // (cheat_score.py); a Post button shows the exact message it posts; a likely-group chip or (Why?)
  // explains the guess; a team's title line shows its average hours and new accounts; the "?"
  // button shows what the colours mean.
  let why = "", short = "", legendTip = "", tip = null, tipOn = null, tipHTML = "", mouse = [0, 0];
  let scores = {};  // sid -> the score's breakdown, from the last render
  let groupNames = {};  // group number -> the names in it
  const seenTone = {};  // sid -> the tone their row had last time it was shown (for the one pulse)
  const RANK = {"": 0, weak: 1, warn: 2, bad: 3};
  const WHY = `<span class="pl-why" tabindex="0">(Why?)</span>`;
  // Thin outline icons, the sidebar's style.
  const LINK = `<svg class="pl-link-i" viewBox="0 0 12 12" aria-hidden="true"><path d="M5 7l2-2"/>` +
    `<path d="M4.6 3.4l1-1a2 2 0 0 1 2.9 0l1.1 1.1a2 2 0 0 1 0 2.9l-1 1"/><path d="M7.4 8.6l-1 1a2 2 0 0 1-2.9 0L2.4 8.5a2 2 0 0 1 0-2.9l1-1"/></svg>`;
  const I_CHAT = `<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M1.5 2.5h11v7.2H6.2L3.4 12V9.7H1.5z"/><path d="M4.2 5.4h5.6M4.2 7.3h3.6"/></svg>`;
  const I_COLS = `<svg viewBox="0 0 14 14" aria-hidden="true"><rect x="1.5" y="2" width="11" height="10"/><path d="M5.3 2v10M8.7 2v10"/></svg>`;
  const I_VOTE = `<svg viewBox="0 0 14 14" aria-hidden="true"><rect x="1.5" y="6.5" width="11" height="6"/><path d="M4.5 6.5V2h5v4.5"/><path d="M5.8 4.3l1 1 1.6-1.8"/></svg>`;
  const I_OUT = `<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M8 2h4v4M12 2L6.5 7.5"/><path d="M10.5 8.5V12h-8.5V3.5h3.5"/></svg>`;
  const chip = n => {
    const names = groupNames[n] || [];
    const text = `Group ${n}. ${short}` + (names.length ? `\nIn it: ${names.join(", ")}` : "");
    return `<span class="pl-grp g${(n - 1) % 6}" data-tip="${esc(text)}" aria-label="${esc(text)}">${LINK}${n}</span>`;
  };
  // A hover that is the exact chat message: data-tiph is where it goes, data-tip the message.
  const sayAttrs = h => h ? ` data-say data-tiph="${esc(h.head || "")}" data-tip="${esc(h.text || "")}"` : "";
  const TIPPED = ".pl-why,.pl-legbtn,[data-tip],[data-tiph],.pl-band[data-sid],tr[data-sid]";

  function scoreHTML(b) {
    const rows = b.rows.map(r =>
      `<div class="cs-r"><b class="${r.up ? "up" : "dn"}${r.proof ? " pf" : ""}">${esc(r.lr)}</b>` +
      `<span>${esc(r.text)}<em> &mdash; ${esc(r.why)}</em></span></div>`).join("");
    return `<div class="cs-s">${esc(b.start)}</div>${rows}` +
      `<div class="cs-e">${esc(b.end)} <i>&rarr;</i> <b>${esc(b.pct)}</b> <span class="cs-w b-${b.band}">${esc(b.words)}</span></div>` +
      (b.note ? `<div class="cs-n">${esc(b.note)}</div>` : "");
  }

  // What an anchor's tooltip says, or "" for none (you have no score).
  function tipFor(anchor) {
    if (anchor.matches(".pl-why")) return esc(why);
    if (anchor.matches(".pl-legbtn")) return legendTip;
    const d = anchor.dataset;
    if (d.tip !== undefined || d.tiph !== undefined) {
      const text = esc(d.tip || "").replace(/\n/g, "<br>");
      return (d.tiph ? `<div class="pl-tiph">${esc(d.tiph)}</div>` : "") +
        (text ? `<div class="${d.say !== undefined ? "pl-saymsg" : ""}">${text}</div>` : "");
    }
    const b = scores[d.sid];
    return b ? scoreHTML(b) : "";
  }

  function showTip(anchor) {
    const html = tipFor(anchor);
    if (!html) { hideTip(); return; }
    if (!tip) {
      tip = document.createElement("div");
      tip.setAttribute("role", "tooltip");
      document.body.appendChild(tip);
    }
    const row = anchor.matches("tr");
    const score = anchor.dataset.sid !== undefined && anchor.dataset.tip === undefined;
    tip.className = "pl-tip" + (score ? " cs-tip" : "") + (anchor.matches(".pl-legbtn") ? " pl-legtip" : "") +
      (anchor.dataset.say !== undefined ? " pl-saytip" : "");
    if (html !== tipHTML || tip.style.display !== "block") { tip.innerHTML = html; tipHTML = html; }
    const moved = tipOn !== anchor;
    tipOn = anchor;
    tip.style.display = "block";
    if (!moved && tip.dataset.placed) return;  // same anchor, fresh numbers: stay where it is
    const r = anchor.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight, pad = 8;
    const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
    // A row or a team's title is as wide as the list: under it, where the mouse is; anything else:
    // centred under it.
    const cx = row || anchor.matches(".thead") ? mouse[0] - 40 : r.left + r.width / 2 - w / 2;
    let x = Math.min(Math.max(pad, cx), vw - w - pad);
    let y = r.bottom + 8;
    if (y + h > vh - pad) y = r.top - h - 8;
    y = Math.min(Math.max(pad, y), vh - h - pad);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
    tip.dataset.placed = "1";
  }

  function hideTip() {
    tipOn = null;
    if (tip) { tip.style.display = "none"; delete tip.dataset.placed; }
  }

  // After a re-render the hovered anchor may have been replaced: follow the mouse to its new copy.
  function refreshTip() {
    if (!tipOn) return;
    if (tipOn.isConnected) { showTip(tipOn); return; }  // the score or the message may have changed
    const el = document.elementFromPoint(mouse[0], mouse[1]);
    const a = el && el.closest(TIPPED);
    if (tip) delete tip.dataset.placed;
    a && a.closest("#p-players") ? showTip(a) : hideTip();
  }

  function set(el, key, html) {
    if (last[key] === html) return false;
    last[key] = html;
    el.innerHTML = html;
    return true;
  }

  function setSwitch(sw, on) {
    sw.dataset.on = on ? "1" : "0";
    sw.setAttribute("aria-checked", on ? "true" : "false");
  }

  function build(sec) {
    sec.innerHTML = `
      <div class="toolbar">
        <div class="chips" id="pl-chips"></div>
        <label class="search"><svg viewBox="0 0 14 14"><circle cx="6" cy="6" r="4.3"/><path d="M9.3 9.3L13 13"/></svg><input id="pl-q" placeholder="Search name" aria-label="Search players" spellcheck="false" autocomplete="off"></label>
        <span class="pl-menuwrap">
          <button class="btn" id="pl-colbtn" aria-haspopup="true">${I_COLS}Columns</button>
          <div class="pl-menu" id="pl-colmenu" hidden></div>
        </span>
        <button class="btn pl-legbtn" id="pl-leg" aria-label="What the colours mean">?</button>
        <span class="grow"></span>
        <span class="pl-hud" title="One thin line at the top of your screen: the enemy line-up, their Medics (MEDIC DOWN - PUSH) and their Spies.">
          <span class="sw" id="pl-hud-sw" data-on="0" role="switch" aria-checked="false" aria-label="Mini HUD" tabindex="0"></span>
          <span class="pl-hudl">Mini HUD</span>
          <button class="btn sm" id="pl-hud-move" title="Press, drag the line where you can read it, then press Done.">Move</button>
        </span>
        <span class="pl-menuwrap">
          <button class="btn" id="pl-saybtn" aria-haspopup="true">${I_CHAT}Post in chat <span class="pl-caret">&#x25BE;</span></button>
          <div class="pl-menu pl-right pl-saymenu" id="pl-saymenu" hidden>
            <button data-lobby="summary">Match highlights</button>
            <button data-lobby="kill_race">Top killers</button>
          </div>
        </span>
      </div>
      <div class="pgrid" id="pl-grid">
        <div class="pnl brk pl-list"><div class="teams" id="pl-teams"></div></div>
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
    // The two toolbar menus: Columns and Post in chat. One open at a time; a click elsewhere closes it.
    const menus = {col: sec.querySelector("#pl-colmenu"), say: sec.querySelector("#pl-saymenu")};
    const openMenu = name => {
      menu = name;
      Object.entries(menus).forEach(([k, m]) => { m.hidden = k !== name; });
    };
    sec.querySelector("#pl-colbtn").addEventListener("click", e => { e.stopPropagation(); openMenu(menu === "col" ? null : "col"); });
    sec.querySelector("#pl-saybtn").addEventListener("click", e => { e.stopPropagation(); openMenu(menu === "say" ? null : "say"); });
    menus.col.addEventListener("click", e => {
      e.stopPropagation();
      const row = e.target.closest("[data-col]");
      if (!row) return;
      row.classList.toggle("on");
      act("players_column", row.dataset.col);
    });
    menus.say.addEventListener("click", e => {
      e.stopPropagation();
      const b = e.target.closest("[data-lobby]");
      if (!b) return;
      openMenu(null);
      act("players_lobby", b.dataset.lobby);
    });
    document.addEventListener("click", () => { if (menu) openMenu(null); });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && menu) openMenu(null); });
    // The Mini HUD (the same actions as the Status page used).
    const sw = sec.querySelector("#pl-hud-sw");
    const flip = () => { setSwitch(sw, sw.dataset.on !== "1"); act("hud_toggle"); };
    sw.addEventListener("click", flip);
    sec.querySelector(".pl-hudl").addEventListener("click", flip);
    sw.addEventListener("keydown", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); flip(); } });
    sec.querySelector("#pl-hud-move").addEventListener("click", () => act("hud_move"));
    sec.addEventListener("mouseover", e => {
      if (e.clientX || e.clientY) mouse = [e.clientX, e.clientY];
      const a = e.target.closest(TIPPED);
      if (a && a !== tipOn) { if (tip) delete tip.dataset.placed; showTip(a); }
    });
    sec.addEventListener("mouseout", e => {
      const a = e.target.closest(TIPPED);
      if (a && a === tipOn && !a.contains(e.relatedTarget)) hideTip();
    });
    sec.addEventListener("focusin", e => {
      const a = e.target.closest(".pl-why,.pl-legbtn,.pl-band[data-sid],button[data-tip]");
      if (a) showTip(a);
    });
    sec.addEventListener("focusout", e => { if (e.target === tipOn) hideTip(); });
    document.addEventListener("mousemove", e => { mouse = [e.clientX, e.clientY]; }, {passive: true});
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
      // A button that doesn't apply is only greyed (aria-disabled), so its hover still says why.
      if (!b || b.getAttribute("aria-disabled") === "true") return;
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
        return `<span class="pn ${c.you ? "you" : ""}" title="${esc(c.t)}">${esc(c.t)}${c.you ? "<small>(you)</small>" : ""}</span>`;
      case "HP":
        if (c.pct === undefined) return c.t ? `<div class="hp"><span class="v" style="color:${c.c}">${esc(c.t)}</span></div>` : "";
        return `<div class="hp"><span class="v" style="color:${c.c}">${esc(c.t)}</span>` +
               `<span class="bar"><i style="width:${c.pct}%;background:${c.c}"></i></span>` +
               `<span class="mx">${c.max ? "/" + c.max : ""}</span></div>`;
      case "K/D":
        return c.k === undefined ? "" :
          `<span class="kd"><span class="k">${esc(c.k)}</span><span class="s">/</span><span class="d">${esc(c.d)}</span></span>`;
      case "Flags": {
        // One stamp with the score inside ("CHEATER 98%"); the reasons are in the row's hover and
        // the card's clue list.
        const t = c.tag;
        return t ? `<span class="pl-stamp t-${t[1] || "weak"}">${esc(t[0])}${t[2] ? `<b>${esc(t[2])}</b>` : ""}</span>`
                 : `<span class="noflag">&mdash;</span>`;
      }
      default:
        return `<span class="pl-oc" style="color:${c.c}" title="${esc(c.t)}">${esc(c.t)}</span>`;
    }
  }

  function teamHTML(t, s) {
    const all = s.all_columns, idx = s.shown.map(c => all.indexOf(c));
    const kind = t.colour === "BLU" ? "blu" : t.colour === "RED" ? "red" : "unk";
    const name = t.name.charAt(0) + t.name.slice(1).toLowerCase();
    const head = s.shown.map(c => {
      const px = widthOf(c), w = px ? ` style="width:${px}px"` : "";
      const arrow = s.sort && s.sort[0] === c ? (s.sort[1] ? " ▼" : " ▲") : "";
      return `<th${w} data-sort="${esc(c)}" class="${arrow ? "srt" : ""}">${esc(s.headers[c])}${arrow}</th>`;
    }).join("");
    const rows = t.rows.map(r => {
      if (r.sub) return `<tr class="pl-sub"><td colspan="${s.shown.length}">${esc(r.sub)}</td></tr>`;
      return `<tr data-sid="${r.sid}" class="${r.sel ? "sel " : ""}${r.tone ? "t-" + r.tone : ""}">` + idx.map((i, n) => {
        const c = s.shown[n];
        const content = c === "Player"
          ? `<span class="pl-pw">${cell(c, r.cells[i])}${r.grp ? chip(r.grp) : ""}</span>`
          : cell(c, r.cells[i]);
        return `<td${c === "Mark" ? ' class="pl-mk"' : ""}>${content}</td>`;
      }).join("") + "</tr>";
    }).join("");
    const lineup = t.lineup.map(([n, what]) => `<span class="lu">${n ? `<b>${esc(n)}</b> ` : ""}${esc(what)}</span>`).join("");
    // Average hours and new accounts: on the title line's hover, to keep the line short.
    const info = (t.info || []).join("\n");
    const flagged = `<span class="fl${t.flagged ? " on" : ""}">${t.flagged} flagged</span>` +
      (t.cheaters ? ` <span class="pl-cheats">(${t.cheaters} cheater${t.cheaters === 1 ? "" : "s"})</span>` : "");
    return `<div class="team ${kind} pl-${t.key === "enemy" ? "enemy" : "mine"}">
      <div class="thead${info ? " pl-hasinfo" : ""}"${info ? ` data-tip="${esc(info)}"` : ""}>
        <span class="tname">${esc(name)}${t.colour ? ` &middot; <em>${esc(t.colour)}</em>` : ""}</span>
        <span class="tmeta"><span class="pl-cnt">${t.count} player${t.count === 1 ? "" : "s"}</span> &middot; ${flagged}` +
          `${t.groups ? ` &middot; <span class="pl-gc">${LINK}${t.groups} group${t.groups === 1 ? "" : "s"} ${WHY}</span>` : ""}</span>
        <span class="lineup">${lineup}</span>
      </div>
      <table class="pt" style="min-width:${s.shown.reduce((sum, c) => sum + widthOf(c), PLAYER_MIN)}px"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  // What the colours mean: the "?" button's hover.
  function legendHTML(s) {
    const hp = s.hp_colours;
    const row = (cls, text) => `<span><i class="${cls}"></i>${text}</span>`;
    const hpRow = (colour, text) => `<span><i style="background:${colour}"></i>${text}</span>`;
    return `<div class="pl-leg"><b>Mark</b>${row("lg-bad", "cheater")}${row("lg-warn", "suspicious")}${row("lg-weak", "weak flag")}` +
      `<b>HP</b>${hpRow(hp.high, "&ge;66%")}${hpRow(hp.mid, "33-66%")}${hpRow(hp.low, "&lt;33%")}${hpRow(hp.over, "overheal")}</div>`;
  }

  // A row that just became flagged (or worse) pulses once; rows seen for the first time don't.
  function pulse(sec, s) {
    s.teams.forEach(t => t.rows.forEach(r => {
      if (!r.sid) return;
      const now = r.tone || "", was = seenTone[r.sid];
      seenTone[r.sid] = now;
      if (was === undefined || RANK[now] <= RANK[was] || RANK[now] < 2) return;
      const tr = sec.querySelector(`#pl-teams tr[data-sid="${r.sid}"]`);
      if (tr) { tr.classList.remove("pl-pulse"); void tr.offsetWidth; tr.classList.add("pl-pulse"); }
    }));
  }

  // --- the selected player: a player card --------------------------------------------------

  function detailHTML(p) {
    const sc = p.score;
    const initial = (p.name.trim()[0] || "?").toUpperCase();
    const av = p.avatar ? `<img src="${p.avatar}" alt="">` : `<span>${esc(initial)}</span>`;
    // The score's band as a big label (hover it for how it adds up); you have none.
    const band = sc ? `<div class="pl-band b-${sc.band} t-${p.tone || "none"}" data-sid="${p.sid}" tabindex="0">` +
      `${esc(sc.words)} <span class="pl-dot">&middot;</span> <b>${esc(sc.pct)}</b></div>` : "";
    // Why flagged, as a receipt: the base rate, each clue with its multiplier on the odds, the score.
    const lines = p.reasons.map(r =>
      `<div class="pl-rc${r.you ? " you" : ""}"><p>${r.you ? `<span class="pl-yours">Your mark</span>` : ""}${esc(r.text)}` +
      `${r.why ? `<small>${esc(r.why)}</small>` : ""}</p><b class="pl-lr ${r.proof ? "pf" : r.up ? "up" : "dn"}" title="What this does to the odds">${esc(r.lr)}</b></div>`).join("");
    const receipt = !sc ? `<div class="pl-none">This is you.</div>` :
      `<div class="pl-rc pl-rc-start"><p>Start: the base rate</p><b>${esc(p.prior)}</b></div>` +
      (lines || `<div class="pl-none">Nothing found: the score is the base rate.</div>`) +
      `<div class="pl-rc pl-rc-total"><p>Cheater score</p><b class="t-${p.tone || "none"}">${esc(sc.pct)}</b></div>`;
    const [acts, says] = p.actions;
    const off = on => on ? "" : ` aria-disabled="true"`;
    const tipOf = h => h ? ` data-tip="${esc(h.text || "")}"` : "";
    const ICON = {kick: I_VOTE, history: I_OUT};
    const actBtn = ([key, text, on, hint]) =>
      `<button class="btn${key === "kick" ? " pl-kick" : key === "history" ? " pl-link" : ""}${on ? "" : " off"}" data-act="${key}"${off(on)}${tipOf(hint)}>` +
      `${key === "kick" ? ICON.kick : ""}${esc(text.replace(" ↗", ""))}${key === "history" ? ICON.history : ""}</button>`;
    const sayBtn = ([key, text, on, hint]) =>
      `<button class="btn${on ? "" : " off"}" data-act="${key}"${off(on)}${sayAttrs(hint)}>${esc(text)}</button>`;
    const [actsLabel, saysLabel] = p.groups || ["Act on them", "Post in chat"];
    return `
     <div class="pl-card">
       <button class="pl-close" data-close title="Close" aria-label="Close">&#x2715;</button>
       <div class="pl-who">
         <span class="pl-av">${av}</span>
         <div class="pl-whot">
           <div class="dname">${esc(p.name)}</div>
           <div class="dsub"><span class="side-t ${p.enemy ? "" : "blu"}">${esc(p.side)}</span>${p.cls ? `<span class="sep">&middot;</span><span>${esc(p.cls)}</span>` : ""}</div>
         </div>
       </div>
       ${band}
       ${p.about ? `<div class="pl-about">${esc(p.about)}</div>` : ""}
       ${p.together ? `<div class="pl-tog">${chip(p.together.n)}<span>Likely together with: ${esc(p.together.names.join(", "))}</span> ${WHY}</div>` : ""}
     </div>
     <div class="pl-receipt"><span class="lab">Why flagged</span><div class="pl-rcs">${receipt}</div></div>
     <div class="pl-actions">
       <span class="lab">${esc(actsLabel)}</span><div class="pl-agrid">${acts.map(actBtn).join("")}</div>
       <span class="lab">${esc(saysLabel)}</span><div class="pl-agrid pl-says">${says.map(sayBtn).join("")}</div>
     </div>`;
  }

  // The toolbar's Post in chat menu: each item with the exact message it would post.
  function postsHTML(posts) {
    return posts.map(m => `<button data-lobby="${esc(m.key)}"><span class="pl-mt">${esc(m.name)}</span>` +
      `<span class="pl-mh">${esc(m.head)}</span>${m.msg ? `<span class="pl-mp">${esc(m.msg)}</span>` : ""}</button>`).join("");
  }

  // --- each render ---------------------------------------------------------------------------

  LS.page("Players", function (s) {
    const sec = document.getElementById("p-players");
    if (!sec || s.error) return;
    if (!built) build(sec);
    why = s.together_why || "";
    short = s.together_short || "";
    legendTip = legendHTML(s);
    groupNames = {};
    (s.groups || []).forEach(g => { groupNames[g.n] = g.names; });
    scores = {};
    s.teams.forEach(t => t.rows.forEach(r => { if (r.score) scores[r.sid] = r.score; }));
    if (s.panel && s.panel.score) scores[s.panel.sid] = s.panel.score;
    set(sec.querySelector("#pl-chips"), "chips", s.filters.map(f =>
      `<button class="chip ${f.key === s.filter ? "on" : ""}" data-f="${f.key}">${esc(f.text)}` +
      `${f.n ? ` <span class="n ${f.key === "cheaters" ? "r" : ""}">${f.n}</span>` : ""}</button>`).join(""));
    const q = sec.querySelector("#pl-q");
    if (document.activeElement !== q && q.value.trim().toLowerCase() !== s.search) q.value = s.search;
    set(sec.querySelector("#pl-colmenu"), "cols", s.columns.map(c =>
      `<button class="${c.on ? "on" : ""}" data-col="${esc(c.key)}"><span class="ck"></span>${esc(c.name)}</button>`).join(""));
    if (s.posts) set(sec.querySelector("#pl-saymenu"), "posts", postsHTML(s.posts));
    const sw = sec.querySelector("#pl-hud-sw");
    setSwitch(sw, s.hud);
    sec.querySelector(".pl-hud").classList.toggle("on", !!s.hud);
    const move = sec.querySelector("#pl-hud-move");
    const moveText = s.hud_moving ? "Done" : "Move";
    if (move.textContent !== moveText) move.textContent = moveText;
    move.classList.toggle("pri", !!s.hud_moving);
    set(sec.querySelector("#pl-teams"), "teams",
      s.empty ? `<div class="empty">${esc(s.empty)}</div>` : s.teams.map(t => teamHTML(t, s)).join(""));
    pulse(sec, s);
    const grid = sec.querySelector("#pl-grid"), detail = sec.querySelector("#pl-detail");
    grid.classList.toggle("pl-nopanel", !s.panel);
    if (s.panel) {
      detail.dataset.tone = s.panel.tone || "";
      set(detail, "detail", detailHTML(s.panel));
    } else set(detail, "detail", "");
    refreshTip();
  });
})();

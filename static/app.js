(() => {
  "use strict";

  const brandName = document.body.dataset.brand || "Anime Index";

  // ---------------------------------------------------------------------
  // Telegram WebApp bootstrap (no-ops gracefully outside Telegram)
  // ---------------------------------------------------------------------
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      tg.setHeaderColor && tg.setHeaderColor("#0a0a0a");
      tg.setBackgroundColor && tg.setBackgroundColor("#0a0a0a");
    } catch (e) { /* not fatal */ }
  }
  const initData = tg ? tg.initData : "";

  function authHeaders() {
    return initData ? { "X-Telegram-Init-Data": initData } : {};
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(options.headers || {}),
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Request failed (${res.status})`);
    }
    return res.json();
  }

  // ---------------------------------------------------------------------
  // Elements
  // ---------------------------------------------------------------------
  const el = (id) => document.getElementById(id);
  const searchInput = el("search-input");
  const trendingRow = el("trending-row");
  const popularGrid = el("popular-grid");
  const letterBar = el("letter-bar");
  const availableGroups = el("available-groups");
  const availableEmpty = el("available-empty");
  const tabAvailable = el("tab-available");
  const tabNews = el("tab-news");
  const tabBtns = document.querySelectorAll(".tab-btn");

  const detailOverlay = el("detail-overlay");
  const detailPoster = el("detail-poster");
  const detailTitle = el("detail-title");
  const detailGenres = el("detail-genres");
  const detailDescription = el("detail-description");
  const detailActionArea = el("detail-action-area");

  const linkOverlay = el("link-overlay");
  const linkInput = el("link-input");

  const reportOverlay = el("report-overlay");
  const reportDetails = el("report-details");
  let selectedReason = null;

  const profileBtn = el("profile-btn");
  const profileView = el("profile-view");
  const profileBack = el("profile-back");
  const profileCard = el("profile-card");
  const appView = el("app-view");

  const toast = el("toast");
  let toastTimer = null;

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.add("hidden"), 2200);
  }

  // ---------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------
  let trending = [];
  let popular = [];
  let available = [];
  let activeLetter = null;
  let query = "";
  let profile = null; // filled in lazily / preloaded for admin checks

  const ALL_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

  // ---------------------------------------------------------------------
  // Poster rendering
  // ---------------------------------------------------------------------
  function posterCard(item, onOpen) {
    const card = document.createElement("div");
    card.className = "poster-card";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = item.poster_url || "";
    img.alt = item.title;
    card.appendChild(img);

    if (item.rating) {
      const badge = document.createElement("span");
      badge.className = "poster-rating";
      badge.textContent = item.rating.toFixed(1);
      card.appendChild(badge);
    }

    const wrap = document.createElement("div");
    wrap.className = "poster-title-wrap";
    const title = document.createElement("p");
    title.className = "poster-title";
    title.textContent = item.title;
    wrap.appendChild(title);
    card.appendChild(wrap);

    card.addEventListener("click", onOpen);
    return card;
  }

  function matchesQuery(title) {
    return !query || title.toLowerCase().includes(query.toLowerCase());
  }

  // ---------------------------------------------------------------------
  // Render: News tab (Trending + Popular, discovery only — no local id)
  // ---------------------------------------------------------------------
  function renderNewsTab() {
    trendingRow.innerHTML = "";
    trending.filter((a) => matchesQuery(a.title)).forEach((item) => {
      trendingRow.appendChild(posterCard(item, () => openDiscoverDetail(item)));
    });

    popularGrid.innerHTML = "";
    popular.filter((a) => matchesQuery(a.title)).forEach((item) => {
      popularGrid.appendChild(posterCard(item, () => openDiscoverDetail(item)));
    });
  }

  // ---------------------------------------------------------------------
  // Render: Available tab (everything posted via /addpost)
  // ---------------------------------------------------------------------
  function lettersWithData() {
    return new Set(available.map((a) => (a.title[0] || "").toUpperCase()));
  }

  function filteredAvailable() {
    let list = available;
    if (query.trim()) {
      list = list.filter((a) => matchesQuery(a.title));
    } else if (activeLetter) {
      list = list.filter((a) => a.title[0].toUpperCase() === activeLetter);
    }
    return [...list].sort((a, b) => a.title.localeCompare(b.title));
  }

  function renderLetterBar() {
    letterBar.innerHTML = "";
    const has = lettersWithData();
    ALL_LETTERS.forEach((l) => {
      const btn = document.createElement("button");
      btn.className = "letter-btn" + (activeLetter === l ? " active" : "");
      btn.textContent = l;
      btn.disabled = !has.has(l);
      btn.addEventListener("click", () => {
        query = "";
        searchInput.value = "";
        activeLetter = activeLetter === l ? null : l;
        renderAvailableTab();
      });
      letterBar.appendChild(btn);
    });
  }

  function renderAvailableTab() {
    renderLetterBar();
    availableGroups.innerHTML = "";
    const list = filteredAvailable();
    availableEmpty.classList.toggle("hidden", list.length !== 0);

    const groups = {};
    list.forEach((a) => {
      const l = a.title[0].toUpperCase();
      (groups[l] = groups[l] || []).push(a);
    });

    Object.keys(groups).sort().forEach((letter) => {
      const wrap = document.createElement("div");
      wrap.className = "letter-group";

      const header = document.createElement("div");
      header.className = "letter-group-header";
      header.innerHTML = `<span class="letter-group-label">${letter}</span><span class="letter-group-line"></span>`;
      wrap.appendChild(header);

      const grid = document.createElement("div");
      grid.className = "grid-2";
      groups[letter].forEach((item) => {
        grid.appendChild(posterCard(item, () => openLocalDetail(item)));
      });
      wrap.appendChild(grid);

      availableGroups.appendChild(wrap);
    });
  }

  // ---------------------------------------------------------------------
  // Tabs
  // ---------------------------------------------------------------------
  function setTab(tab) {
    tabBtns.forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    tabAvailable.classList.toggle("hidden", tab !== "available");
    tabNews.classList.toggle("hidden", tab !== "news");
    if (tab === "available") renderAvailableTab();
  }
  tabBtns.forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));

  searchInput.addEventListener("input", (e) => {
    query = e.target.value;
    if (query) activeLetter = null;
    renderNewsTab();
    if (!tabAvailable.classList.contains("hidden")) renderAvailableTab();
  });

  // ---------------------------------------------------------------------
  // Detail sheet
  // ---------------------------------------------------------------------
  let currentDetail = null; // the anime currently shown in the sheet
  let currentContext = null; // "available" | "news"

  function openDetailSheet(anime, context) {
    currentDetail = anime;
    currentContext = context;
    detailPoster.src = anime.banner_url || anime.poster_url || "";
    detailTitle.textContent = anime.title;
    detailDescription.textContent = anime.description || "No synopsis available.";
    detailDescription.scrollTop = 0;

    detailGenres.innerHTML = "";
    (anime.genres || []).forEach((g) => {
      const pill = document.createElement("span");
      pill.className = "genre-pill";
      pill.textContent = g;
      detailGenres.appendChild(pill);
    });

    renderDetailAction(anime, context);
    detailOverlay.classList.remove("hidden");
  }

  function closeDetailSheet() {
    detailOverlay.classList.add("hidden");
    currentDetail = null;
    currentContext = null;
  }
  el("detail-close").addEventListener("click", closeDetailSheet);
  detailOverlay.addEventListener("click", (e) => {
    if (e.target === detailOverlay) closeDetailSheet();
  });

  function renderDetailAction(anime, context) {
    detailActionArea.innerHTML = "";

    // News tab items are pure discovery (not tied to a local post) — no
    // Join / Request action, just the info + Report an issue.
    if (context === "news") return;

    const row = document.createElement("div");
    row.className = "action-row";

    if (anime.join_link) {
      const joinBtn = document.createElement("button");
      joinBtn.className = "btn btn-primary";
      joinBtn.textContent = "\u25b6 Join";
      joinBtn.addEventListener("click", () => {
        if (tg && tg.openLink) tg.openLink(anime.join_link);
        else window.open(anime.join_link, "_blank");
      });
      row.appendChild(joinBtn);
    } else {
      const reqBtn = document.createElement("button");
      reqBtn.className = "btn btn-primary";
      reqBtn.textContent = "Request Anime";
      reqBtn.addEventListener("click", () => submitRequest(anime.title, reqBtn));
      row.appendChild(reqBtn);
    }

    // Admin/owner-only control to set or change the join link.
    if (profile && profile.role === "admin" && anime.id) {
      const plus = document.createElement("button");
      plus.className = "plus-btn";
      plus.textContent = "+";
      plus.setAttribute("aria-label", "Set join link");
      plus.addEventListener("click", () => openLinkSheet(anime));
      row.appendChild(plus);
    }

    detailActionArea.appendChild(row);
  }

  async function submitRequest(title, btn) {
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
      await api("/api/request", { method: "POST", body: JSON.stringify({ title }) });
      btn.textContent = "Request sent \u2713";
      showToast("Request sent — you'll be notified once it's added.");
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Request Anime";
      showToast(err.message || "Couldn't send request");
    }
  }

  // Opens an item that already lives in the local library (Available tab —
  // full data, including description/genres, is already on the object).
  function openLocalDetail(item) {
    openDetailSheet(item, "available");
  }

  // Opens a Trending/Popular card — only lightweight data was loaded for
  // the grid, so fetch full AniList details (genres/synopsis/banner) first.
  async function openDiscoverDetail(item) {
    openDetailSheet({ ...item, description: "Loading synopsis...", genres: [] }, "news");
    try {
      const full = await api(`/api/anilist/${item.anilist_id}`);
      if (currentDetail && currentDetail.title === item.title) {
        openDetailSheet({ ...full, rating: item.rating ?? full.rating }, "news");
      }
    } catch (err) {
      if (currentDetail) detailDescription.textContent = "Couldn't load full details.";
    }
  }

  // ---------------------------------------------------------------------
  // Set Join Link sheet (admin only)
  // ---------------------------------------------------------------------
  let linkTargetAnime = null;

  function openLinkSheet(anime) {
    linkTargetAnime = anime;
    linkInput.value = anime.join_link || "";
    linkOverlay.classList.remove("hidden");
    linkInput.focus();
  }

  function closeLinkSheet() {
    linkOverlay.classList.add("hidden");
    linkTargetAnime = null;
  }

  el("link-cancel").addEventListener("click", closeLinkSheet);
  linkOverlay.addEventListener("click", (e) => {
    if (e.target === linkOverlay) closeLinkSheet();
  });

  el("link-save").addEventListener("click", async () => {
    if (!linkTargetAnime) return;
    const value = linkInput.value.trim();
    try {
      await api(`/api/anime/${linkTargetAnime.id}/link`, {
        method: "PATCH",
        body: JSON.stringify({ link: value }),
      });
      linkTargetAnime.join_link = value;
      if (currentDetail && currentDetail.id === linkTargetAnime.id) {
        currentDetail.join_link = value;
        renderDetailAction(currentDetail, currentContext);
      }
      closeLinkSheet();
      showToast("Link saved");
      await loadAvailable();
    } catch (err) {
      showToast(err.message || "Couldn't save link");
    }
  });

  // ---------------------------------------------------------------------
  // Report sheet
  // ---------------------------------------------------------------------
  el("report-open-btn").addEventListener("click", () => {
    selectedReason = null;
    reportDetails.value = "";
    document.querySelectorAll(".reason-btn").forEach((b) => b.classList.remove("selected"));
    reportOverlay.classList.remove("hidden");
  });

  document.querySelectorAll(".reason-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedReason = btn.dataset.reason;
      document.querySelectorAll(".reason-btn").forEach((b) => b.classList.remove("selected"));
      btn.classList.add("selected");
    });
  });

  el("report-cancel").addEventListener("click", () => reportOverlay.classList.add("hidden"));
  reportOverlay.addEventListener("click", (e) => {
    if (e.target === reportOverlay) reportOverlay.classList.add("hidden");
  });

  el("report-submit").addEventListener("click", async () => {
    if (!selectedReason) {
      showToast("Pick a reason first");
      return;
    }
    if (!currentDetail) return;
    try {
      await api("/api/report", {
        method: "POST",
        body: JSON.stringify({
          anime_id: currentDetail.id || null,
          anime_title: currentDetail.title,
          reason: selectedReason,
          details: reportDetails.value.trim(),
        }),
      });
      reportOverlay.classList.add("hidden");
      showToast("Report submitted — thank you.");
    } catch (err) {
      showToast(err.message || "Couldn't submit report");
    }
  });

  // ---------------------------------------------------------------------
  // Profile
  // ---------------------------------------------------------------------
  function initials(name) {
    return (name || "?").trim().charAt(0).toUpperCase();
  }

  async function openProfile() {
    appView.classList.add("hidden");
    profileView.classList.remove("hidden");
    profileCard.innerHTML = `<p class="profile-hint">Loading profile\u2026</p>`;
    try {
      profile = await api("/api/profile");
      const displayName = profile.first_name || profile.username || "User";
      profileCard.innerHTML = `
        <div class="profile-header">
          <div class="profile-avatar">${initials(displayName)}</div>
          <div>
            <div class="profile-name">${escapeHtml(displayName)}</div>
            <div class="profile-username">${profile.username ? "@" + escapeHtml(profile.username) : "no username"}</div>
          </div>
        </div>
        <div class="profile-row"><span class="label">Telegram ID</span><span class="value">${profile.telegram_id}</span></div>
        <div class="profile-row"><span class="label">Registered in bot</span><span class="value">yes</span></div>
        <div class="profile-row"><span class="label">Role</span><span class="value">${escapeHtml(profile.role)}</span></div>
        <div class="profile-row"><span class="label">Access</span><span class="value">${escapeHtml(profile.access)}</span></div>
      `;
    } catch (err) {
      profileCard.innerHTML = `<p class="profile-hint">${escapeHtml(err.message || "Open this from inside Telegram to view your profile.")}</p>`;
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  profileBtn.addEventListener("click", openProfile);
  profileBack.addEventListener("click", () => {
    profileView.classList.add("hidden");
    appView.classList.remove("hidden");
  });

  // ---------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------
  async function loadNews() {
    try {
      [trending, popular] = await Promise.all([
        api("/api/catalog/trending"),
        api("/api/catalog/popular"),
      ]);
    } catch (err) {
      trending = [];
      popular = [];
    }
    renderNewsTab();
  }

  async function loadAvailable() {
    try {
      available = await api("/api/catalog/available");
    } catch (err) {
      available = [];
    }
    if (!tabAvailable.classList.contains("hidden")) renderAvailableTab();
  }

  // Load profile up front (silently) so the admin "+" control can appear
  // without waiting for the user to open the Profile screen.
  async function preloadProfile() {
    try {
      profile = await api("/api/profile");
    } catch (err) {
      profile = null;
    }
  }

  (async function init() {
    document.title = brandName;
    await Promise.all([loadNews(), loadAvailable(), preloadProfile()]);
    renderAvailableTab();
  })();
})();

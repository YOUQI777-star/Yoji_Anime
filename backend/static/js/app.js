(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  const dom = {
    body: document.body,

    brandHomeBtn: $("#brandHomeBtn"),
    guideToggleBtn: $("#guideToggleBtn"),
    guideCloseBtn: $("#guideCloseBtn"),
    guideDrawer: $("#guideDrawer"),

    searchForm: $("#searchForm"),
    searchInput: $("#searchInput"),
    searchBtn: $("#searchBtn"),
    scopeSelect: $("#scopeSelect"),
    displayLangSelect: $("#displayLangSelect"),
    uiLangSelect: $("#uiLangSelect"),

    autocompleteList: $("#autocompleteList"),
    autocompleteAnimeGroup: $("#autocompleteAnimeGroup"),
    autocompleteCharacterGroup: $("#autocompleteCharacterGroup"),
    autocompleteVAGroup: $("#autocompleteVAGroup"),

    historyBtn: $("#historyBtn"),
    favoritesBtn: $("#favoritesBtn"),
    authBtn: $("#authBtn"),

    heroBanner: $("#heroBanner"),
    heroExploreBtn: $("#heroExploreBtn"),
    heroAskBtn: $("#heroAskBtn"),
    heroIdentifyBtn: $("#heroIdentifyBtn"),

    graphContainer: $("#graphContainer"),
    cy: $("#cy"),
    graphEmptyState: $("#graphEmptyState"),
    graphLoading: $("#graphLoading"),
    graphStatus: $("#graphStatus"),
    fitGraphBtn: $("#fitGraphBtn"),
    resetGraphBtn: $("#resetGraphBtn"),
    clearGraphBtn: $("#clearGraphBtn"),
    zoomInBtn: $("#zoomInBtn"),
    zoomOutBtn: $("#zoomOutBtn"),

    welcomeCard: $("#welcomeCard"),
    detailPanel: $("#detailPanel"),
    liteDetailPanel: $("#liteDetailPanel"),
    recommendationPanel: $("#recommendationPanel"),
    identifyCard: $("#identifyCard"),
    authCard: $("#authCard"),
    favoritesCard: $("#favoritesCard"),
    historyCard: $("#historyCard"),

    quickExploreCard: $("#quickExploreCard"),
    quickAskCard: $("#quickAskCard"),
    quickIdentifyCard: $("#quickIdentifyCard"),

    detailTabButtons: $$("[data-detail-tab]"),
    detailTabPanels: $$("[data-tab-panel]"),

    authTabButtons: $$("[data-auth-tab]"),
    authPanels: $$("[data-auth-panel]"),

    recommendBtn: $("#recommendBtn"),
    favoriteBtn: $("#favoriteBtn"),
    expandSeriesBtn: $("#expandSeriesBtn"),

    askForm: $("#askForm"),
    askInput: $("#askInput"),
    askSendBtn: $("#askSendBtn"),
    aiChatLog: $("#aiChatLog"),
    askContextChip: $("#askContextChip"),

    identifyForm: $("#identifyForm"),
    identifyFileInput: $("#identifyFileInput"),
    identifyResult: $("#identifyResult"),

    loginForm: $("#loginForm"),
    registerForm: $("#registerForm"),
    loginUsername: $("#loginUsername"),
    loginPassword: $("#loginPassword"),
    registerUsername: $("#registerUsername"),
    registerPassword: $("#registerPassword"),
    authStatus: $("#authStatus"),

    historyList: $("#historyList")
  };

  const appState = {
    uiLang: "zh",
    displayLang: "cn",
    currentGraph: { nodes: [], edges: [] },
    currentNode: null,
    currentAnimeId: null,
    focusNodeId: null,
    selectedNodeId: null,
    currentScope: "all",
    autocompleteTimer: null,
    favorites: {
      anime: [],
      characters: [],
      voice_actors: []
    },
    history: []
  };

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    bindEvents();
    initGraph();
    switchMainPanel("welcome");
    hide(dom.autocompleteList);
    setGraphReady("图谱已就绪");
    loadInitialData();
  }

  function bindEvents() {
    dom.guideToggleBtn?.addEventListener("click", openGuide);
    dom.guideCloseBtn?.addEventListener("click", closeGuide);

    dom.brandHomeBtn?.addEventListener("click", goHome);
    dom.brandHomeBtn?.addEventListener("keydown", (evt) => {
      if (evt.key === "Enter" || evt.key === " ") {
        evt.preventDefault();
        goHome();
      }
    });

    dom.searchForm?.addEventListener("submit", onSearchSubmit);
    dom.searchInput?.addEventListener("input", onSearchInput);
    dom.searchInput?.addEventListener("focus", onSearchInput);
    dom.searchInput?.addEventListener("blur", () => {
      window.setTimeout(() => hide(dom.autocompleteList), 180);
    });

    dom.scopeSelect?.addEventListener("change", () => {
      appState.currentScope = dom.scopeSelect?.value || "all";
    });

    dom.displayLangSelect?.addEventListener("change", () => {
      appState.displayLang = dom.displayLangSelect?.value || "cn";
    });

    dom.uiLangSelect?.addEventListener("change", () => {
      appState.uiLang = dom.uiLangSelect?.value || "zh";
      document.documentElement.setAttribute("data-ui-lang", appState.uiLang);
    });

    dom.heroExploreBtn?.addEventListener("click", focusSearchInput);
    dom.heroAskBtn?.addEventListener("click", () => {
      switchMainPanel(appState.currentNode ? "detail" : "welcome");
      dom.askInput?.focus();
    });
    dom.heroIdentifyBtn?.addEventListener("click", () => switchMainPanel("identify"));

    dom.quickExploreCard?.addEventListener("click", focusSearchInput);
    dom.quickAskCard?.addEventListener("click", () => {
      switchMainPanel(appState.currentNode ? "detail" : "welcome");
      dom.askInput?.focus();
    });
    dom.quickIdentifyCard?.addEventListener("click", () => switchMainPanel("identify"));

    dom.fitGraphBtn?.addEventListener("click", () => window.YojiGraph?.fit?.());
    dom.resetGraphBtn?.addEventListener("click", () => window.YojiGraph?.resetView?.());
    dom.clearGraphBtn?.addEventListener("click", clearAllGraphState);

    dom.zoomInBtn?.addEventListener("click", () => zoomGraph(1.15));
    dom.zoomOutBtn?.addEventListener("click", () => zoomGraph(0.87));

    dom.detailTabButtons.forEach((btn) => {
      btn.addEventListener("click", () => activateDetailTab(btn.dataset.detailTab));
    });

    dom.authTabButtons.forEach((btn) => {
      btn.addEventListener("click", () => activateAuthTab(btn.dataset.authTab));
    });

    dom.recommendBtn?.addEventListener("click", onRecommendClick);
    dom.favoriteBtn?.addEventListener("click", onFavoriteClick);
    dom.expandSeriesBtn?.addEventListener("click", onExpandSeriesClick);

    dom.askForm?.addEventListener("submit", onAskSubmit);
    dom.identifyForm?.addEventListener("submit", onIdentifySubmit);
    dom.loginForm?.addEventListener("submit", onLoginSubmit);
    dom.registerForm?.addEventListener("submit", onRegisterSubmit);

    dom.historyBtn?.addEventListener("click", async () => {
      await loadHistory();
      switchMainPanel("history");
    });
    dom.favoritesBtn?.addEventListener("click", onFavoritesOpen);
    dom.authBtn?.addEventListener("click", () => switchMainPanel("auth"));

    document.addEventListener("click", (evt) => {
      if (!dom.guideDrawer?.contains(evt.target) && evt.target !== dom.guideToggleBtn) {
        if (!dom.guideDrawer?.classList.contains("hidden")) closeGuide();
      }
    });
  }

  function initGraph() {
    if (!dom.cy || !window.YojiGraph?.init) return;

    window.YojiGraph.init(dom.cy, {
      onNodeClick: handleNodeClick,
      onNodeDoubleClick: handleNodeDoubleClick,
      onCanvasClick: handleCanvasClick
    });
  }

  async function loadInitialData() {
    await Promise.allSettled([loadFavorites(), loadHistory()]);
  }

  async function loadFavorites() {
    if (!window.YojiAPI?.getFavorites) return;
    try {
      const data = await window.YojiAPI.getFavorites();
      appState.favorites = data || {
        anime: [],
        characters: [],
        voice_actors: []
      };
      window.YojiPanel?.renderFavorites?.(appState.favorites);
    } catch (err) {
      console.warn("Favorites load failed:", err.message);
    }
  }

  async function loadHistory() {
    if (!window.YojiAPI?.getHistory) return;
    try {
      const data = await window.YojiAPI.getHistory();
      appState.history = Array.isArray(data)
        ? data
        : data?.items || data?.history || [];
      renderHistory(appState.history);
    } catch (err) {
      console.warn("History load failed:", err.message);
    }
  }

  async function onSearchSubmit(evt) {
    evt?.preventDefault?.();

    const q = (dom.searchInput?.value || "").trim();
    if (!q) return;

    setGraphLoading(true);
    setGraphReady("搜索中...");

    try {
      const data = await window.YojiAPI.searchAnime(q, appState.currentScope || "all", 30);
      const graphPayload = normalizeGraphPayload(data, { fallbackType: "Anime" });

      appState.currentGraph = graphPayload;
      appState.currentNode = firstGraphNode(graphPayload);
      appState.focusNodeId = appState.currentNode?.id || null;
      appState.selectedNodeId = appState.currentNode?.id || null;
      appState.currentAnimeId =
        normalizeType(appState.currentNode?.type) === "Anime"
          ? appState.currentNode?.id || null
          : appState.currentAnimeId;

      renderGraphPayload(graphPayload, {
        focusNodeId: appState.focusNodeId,
        selectedNodeId: appState.selectedNodeId
      });

      if (appState.currentNode) {
        renderNodeDetail(appState.currentNode, {
          graph: graphPayload,
          detail: data?.detail || data?.node || {},
          cover: data?.cover || {},
          relations: data?.relations || {}
        });
        await addToHistory(appState.currentNode);
      } else {
        switchMainPanel("welcome");
      }

      hide(dom.autocompleteList);
      hideHeroIfGraphReady();
      setGraphReady("搜索完成");
    } catch (err) {
      console.error(err);
      setGraphReady("搜索失败");
      showInlineMessage(dom.graphStatus, err.message || "Search failed");
    } finally {
      setGraphLoading(false);
    }
  }

  function onSearchInput() {
    const q = (dom.searchInput?.value || "").trim();
    if (!q) {
      clearAutocomplete();
      hide(dom.autocompleteList);
      return;
    }

    if (appState.autocompleteTimer) clearTimeout(appState.autocompleteTimer);

    appState.autocompleteTimer = window.setTimeout(async () => {
      try {
        const data = await window.YojiAPI.autocomplete(
          q,
          dom.scopeSelect?.value || "all",
          8
        );
        renderAutocomplete(data);
      } catch (err) {
        console.warn("Autocomplete failed:", err.message);
      }
    }, 220);
  }

  function renderAutocomplete(data) {
    const anime = data?.anime || data?.animes || [];
    const character = data?.character || data?.characters || [];
    const va = data?.va || data?.voice_actors || data?.voiceActors || [];

    renderAutocompleteGroup(dom.autocompleteAnimeGroup, anime, "Anime");
    renderAutocompleteGroup(dom.autocompleteCharacterGroup, character, "Character");
    renderAutocompleteGroup(dom.autocompleteVAGroup, va, "Voice Actor");

    if (anime.length || character.length || va.length) show(dom.autocompleteList);
    else hide(dom.autocompleteList);
  }

  function renderAutocompleteGroup(container, items, typeLabel) {
    if (!container) return;
    container.innerHTML = "";
    if (!Array.isArray(items) || items.length === 0) return;

    const title = document.createElement("div");
    title.className = "autocomplete-title";
    title.textContent = typeLabel;
    container.appendChild(title);

    items.forEach((item) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "autocomplete-item";

      const text =
        pickText(
          item.name_cn,
          item.title_cn,
          item.display_name_cn,
          item.name,
          item.title,
          item.label,
          item.id
        ) || "—";

      row.textContent = text;
      row.addEventListener("click", async () => {
        if (dom.searchInput) dom.searchInput.value = text;
        hide(dom.autocompleteList);

        const type = normalizeType(item.type || inferAutocompleteType(typeLabel));
        if (type === "Anime") await onSearchSubmit(new Event("submit"));
        else if (type === "Character") await searchCharacterDirect(text);
        else if (type === "VoiceActor") await searchCastingDirect(text);
      });

      container.appendChild(row);
    });
  }

  async function searchCharacterDirect(name) {
    if (!name) return;

    setGraphLoading(true);
    setGraphReady("角色搜索中...");

    try {
      const data = await window.YojiAPI.searchCharacter(name, 12);
      const graphPayload = normalizeGraphPayload(data, { fallbackType: "Character" });

      appState.currentGraph = graphPayload;
      appState.currentNode = firstGraphNode(graphPayload);
      appState.focusNodeId = appState.currentNode?.id || null;
      appState.selectedNodeId = appState.currentNode?.id || null;

      renderGraphPayload(graphPayload, {
        focusNodeId: appState.focusNodeId,
        selectedNodeId: appState.selectedNodeId
      });

      if (appState.currentNode) {
        renderNodeDetail(appState.currentNode, {
          graph: graphPayload,
          detail: data?.detail || data?.node || {}
        });
        await addToHistory(appState.currentNode);
      }

      hideHeroIfGraphReady();
      setGraphReady("角色搜索完成");
    } catch (err) {
      console.error(err);
      setGraphReady("角色搜索失败");
    } finally {
      setGraphLoading(false);
    }
  }

  async function searchCastingDirect(name) {
    if (!name) return;

    setGraphLoading(true);
    setGraphReady("声优搜索中...");

    try {
      const data = await window.YojiAPI.searchCasting(name, 10);
      const graphPayload = normalizeGraphPayload(data, { fallbackType: "VoiceActor" });

      appState.currentGraph = graphPayload;
      appState.currentNode = firstGraphNode(graphPayload);
      appState.focusNodeId = appState.currentNode?.id || null;
      appState.selectedNodeId = appState.currentNode?.id || null;

      renderGraphPayload(graphPayload, {
        focusNodeId: appState.focusNodeId,
        selectedNodeId: appState.selectedNodeId
      });

      if (appState.currentNode) {
        renderNodeDetail(appState.currentNode, {
          graph: graphPayload,
          detail: data?.detail || data?.node || {}
        });
        await addToHistory(appState.currentNode);
      }

      hideHeroIfGraphReady();
      setGraphReady("声优搜索完成");
    } catch (err) {
      console.error(err);
      setGraphReady("声优搜索失败");
    } finally {
      setGraphLoading(false);
    }
  }

  async function handleNodeDoubleClick(nodeData) {
    if (!nodeData?.id) return;

    setGraphLoading(true);
    setGraphReady("扩展中...");

    try {
      const data = await window.YojiAPI.expandNode(nodeData.raw_id || nodeData.id, nodeData.type || "", 20);
      const expanded = normalizeGraphPayload(data, { fallbackType: nodeData.type || "Node" });
      const merged = mergeGraphPayload(appState.currentGraph, expanded);

      appState.currentGraph = merged;
      appState.focusNodeId = nodeData.id;
      appState.selectedNodeId = nodeData.id;

      renderGraphPayload(merged, {
        focusNodeId: appState.focusNodeId,
        selectedNodeId: appState.selectedNodeId,
        preservePositions: true
      });

      setGraphReady("扩展完成");
    } catch (err) {
      console.error(err);
      setGraphReady("扩展失败");
    } finally {
      setGraphLoading(false);
    }
  }

  function handleNodeClick(nodeData) {
    if (!nodeData) return;

    const cleanNode = nodeData?.data ? nodeData.data : nodeData;
    appState.currentNode = cleanNode;
    appState.selectedNodeId = cleanNode.id || null;
    appState.focusNodeId = cleanNode.id || appState.focusNodeId;

    renderNodeDetail(cleanNode, {
      graph: appState.currentGraph,
      focusNodeId: appState.focusNodeId
    });

    addToHistory(cleanNode);
  }

  function handleCanvasClick() {
    appState.selectedNodeId = null;
  }

  function renderNodeDetail(nodeData, extras = {}) {
    const type = normalizeType(nodeData?.type || nodeData?.label || "Node");

    if (type === "Anime") {
      window.YojiPanel?.renderAnimeDetail?.(nodeData, extras, {
        focusNodeId: appState.focusNodeId,
        currentNodeId: appState.currentNode?.id,
        onRelationClick: handleRelationClick,
        onRecommendationClick: handleRecommendationClick
      });
      switchMainPanel("detail");
      appState.currentAnimeId = nodeData.id || appState.currentAnimeId;
    } else {
      window.YojiPanel?.renderLiteDetail?.(nodeData, extras, {
        focusNodeId: appState.focusNodeId
      });
      switchMainPanel("lite");
    }

    if (dom.askContextChip) {
      dom.askContextChip.textContent =
        pickText(
          nodeData.name_cn,
          nodeData.title_cn,
          nodeData.name,
          nodeData.title,
          nodeData.label,
          nodeData.id
        ) || "当前节点";
    }

    activateDetailTab("info");
  }

  async function onRecommendClick() {
    if (!appState.currentAnimeId) return;

    try {
      const data = await window.YojiAPI.recommendAnime(appState.currentAnimeId, 12);
      window.YojiPanel?.renderRecommendations?.(data, {
        onRecommendationClick: handleRecommendationClick
      });
      switchMainPanel("recommendation");
    } catch (err) {
      console.error(err);
    }
  }

  function handleRecommendationClick(item) {
    if (!item) return;

    const syntheticNode = {
      id: item.id || item.anime_id || item.raw_id,
      type: "Anime",
      name: item.name,
      name_cn: item.name_cn,
      title: item.title,
      title_cn: item.title_cn,
      label: item.name_cn || item.title_cn || item.name || item.title || item.id
    };

    appState.currentNode = syntheticNode;
    appState.currentAnimeId = syntheticNode.id;
    appState.focusNodeId = syntheticNode.id;
    appState.selectedNodeId = syntheticNode.id;

    if (dom.searchInput) dom.searchInput.value = syntheticNode.label || "";
    onSearchSubmit(new Event("submit"));
  }

  function handleRelationClick(item) {
    if (!item) return;
    const targetText =
      pickText(
        item.name_cn,
        item.title_cn,
        item.display_name_cn,
        item.name,
        item.title,
        item.label
      ) || "";

    if (!targetText) return;
    if (dom.searchInput) dom.searchInput.value = targetText;
    onSearchSubmit(new Event("submit"));
  }

  async function onExpandSeriesClick() {
    if (!appState.currentNode?.id) return;
    await handleNodeDoubleClick(appState.currentNode);
  }

  async function onAskSubmit(evt) {
    evt.preventDefault();

    const question = (dom.askInput?.value || "").trim();
    if (!question) return;

    appendChatMessage("user", question);
    if (dom.askInput) dom.askInput.value = "";

    try {
      const data = await window.YojiAPI.askAI(question, {
        anime_id: appState.currentAnimeId,
        node_id: appState.currentNode?.id,
        node_type: appState.currentNode?.type
      });

      const answer =
        data?.answer || data?.response || data?.message || "No answer returned.";
      appendChatMessage("assistant", answer);
      activateDetailTab("ask");
      switchMainPanel(normalizeType(appState.currentNode?.type) === "Anime" ? "detail" : "lite");
    } catch (err) {
      appendChatMessage("assistant", err.message || "Ask AI failed.");
    }
  }

  async function onIdentifySubmit(evt) {
    evt.preventDefault();

    const file = dom.identifyFileInput?.files?.[0];
    if (!file) return;

    try {
      const data = await window.YojiAPI.identifyAnime(file);
      const matches = data?.matches || [];
      const text = matches.length
        ? matches.map(m => `${m.anime_name || 'Unknown'} (${Math.round((m.similarity || 0) * 100)}%)`).join('\n')
        : data?.result || data?.answer || data?.message || JSON.stringify(data);
      if (dom.identifyResult) dom.identifyResult.textContent = text;
      show(dom.identifyResult);
      switchMainPanel("identify");
    } catch (err) {
      if (dom.identifyResult) dom.identifyResult.textContent = err.message || "Identify failed.";
      show(dom.identifyResult);
    }
  }

  async function onLoginSubmit(evt) {
    evt.preventDefault();

    try {
      const data = await window.YojiAPI.login(
        dom.loginUsername?.value || "",
        dom.loginPassword?.value || ""
      );
      if (dom.authStatus) dom.authStatus.textContent = data?.message || "Login success.";
      show(dom.authStatus);
      await loadFavorites();
    } catch (err) {
      if (dom.authStatus) dom.authStatus.textContent = err.message || "Login failed.";
      show(dom.authStatus);
    }
  }

  async function onRegisterSubmit(evt) {
    evt.preventDefault();

    try {
      const data = await window.YojiAPI.register(
        dom.registerUsername?.value || "",
        dom.registerPassword?.value || ""
      );
      if (dom.authStatus) dom.authStatus.textContent = data?.message || "Register success.";
      show(dom.authStatus);
      await loadFavorites();
    } catch (err) {
      if (dom.authStatus) dom.authStatus.textContent = err.message || "Register failed.";
      show(dom.authStatus);
    }
  }

  async function onFavoritesOpen() {
    await loadFavorites();
    switchMainPanel("favorites");
  }

  async function onFavoriteClick() {
    if (!appState.currentNode) return;

    try {
      await window.YojiAPI.addFavorite({
        id: appState.currentNode.id,
        type: appState.currentNode.type,
        name: appState.currentNode.name,
        name_cn: appState.currentNode.name_cn,
        title: appState.currentNode.title,
        title_cn: appState.currentNode.title_cn
      });
      await loadFavorites();
      if (dom.graphStatus) dom.graphStatus.textContent = "已加入收藏";
    } catch (err) {
      console.error(err);
      showInlineMessage(dom.graphStatus, err.message || "Add favorite failed");
    }
  }

  async function addToHistory(node) {
    if (!node?.id) return;

    const entry = {
      id: node.id,
      type: normalizeType(node.type),
      name: node.name,
      name_cn: node.name_cn,
      title: node.title,
      title_cn: node.title_cn,
      label: node.name_cn || node.title_cn || node.name || node.title || node.label
    };

    appState.history = [
      entry,
      ...appState.history.filter(
        (item) => !(String(item.id) === String(entry.id) && String(item.type) === String(entry.type))
      )
    ].slice(0, 20);

    renderHistory(appState.history);

    try {
      await window.YojiAPI.addHistory(entry);
    } catch (err) {
      console.warn("History sync skipped:", err.message);
    }
  }

  function renderHistory(items) {
    if (!dom.historyList) return;
    dom.historyList.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      const empty = document.createElement("div");
      empty.className = "muted-text";
      empty.textContent = "No recent history.";
      dom.historyList.appendChild(empty);
      return;
    }

    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "history-item";

      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent =
        item.label || item.name_cn || item.title_cn || item.name || item.title || item.id;

      const meta = document.createElement("div");
      meta.className = "item-meta";
      meta.textContent = normalizeType(item.type || "Node");

      row.appendChild(title);
      row.appendChild(meta);

      row.addEventListener("click", () => {
        const type = normalizeType(item.type || "Node");
        if (type === "Anime") {
          if (dom.searchInput) dom.searchInput.value = title.textContent;
          onSearchSubmit(new Event("submit"));
        } else if (type === "Character") {
          searchCharacterDirect(title.textContent);
        } else if (type === "VoiceActor") {
          searchCastingDirect(title.textContent);
        }
      });

      dom.historyList.appendChild(row);
    });
  }

  function appendChatMessage(role, text) {
    if (!dom.aiChatLog) return;

    const placeholder = dom.aiChatLog.querySelector(".chat-placeholder");
    if (placeholder) placeholder.remove();

    const msg = document.createElement("div");
    msg.className = `chat-message ${role}`;
    msg.textContent = text;
    dom.aiChatLog.appendChild(msg);
    dom.aiChatLog.scrollTop = dom.aiChatLog.scrollHeight;
  }

  function activateDetailTab(tabName = "info") {
    dom.detailTabButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.detailTab === tabName);
    });
    dom.detailTabPanels.forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.tabPanel === tabName);
    });
  }

  function activateAuthTab(tabName = "login") {
    dom.authTabButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.authTab === tabName);
    });
    dom.authPanels.forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.authPanel === tabName);
    });
  }

  function switchMainPanel(target) {
    hide(dom.welcomeCard);
    hide(dom.detailPanel);
    hide(dom.liteDetailPanel);
    hide(dom.recommendationPanel);
    hide(dom.identifyCard);
    hide(dom.authCard);
    hide(dom.favoritesCard);
    hide(dom.historyCard);

    if (target === "detail") show(dom.detailPanel);
    else if (target === "lite") show(dom.liteDetailPanel);
    else if (target === "recommendation") show(dom.recommendationPanel);
    else if (target === "identify") show(dom.identifyCard);
    else if (target === "auth") show(dom.authCard);
    else if (target === "favorites") show(dom.favoritesCard);
    else if (target === "history") show(dom.historyCard);
    else show(dom.welcomeCard);
  }

  function openGuide() {
    show(dom.guideDrawer);
  }

  function closeGuide() {
    hide(dom.guideDrawer);
  }

  function goHome() {
    switchMainPanel("welcome");
    show(dom.heroBanner);
  }

  function focusSearchInput() {
    dom.searchInput?.focus();
    show(dom.heroBanner);
  }

  function hideHeroIfGraphReady() {
    if (appState.currentGraph?.nodes?.length) {
      hide(dom.heroBanner);
      hide(dom.graphEmptyState);
    }
  }

  function clearAllGraphState() {
    window.YojiGraph?.clearGraph?.();
    appState.currentGraph = { nodes: [], edges: [] };
    appState.currentNode = null;
    appState.currentAnimeId = null;
    appState.focusNodeId = null;
    appState.selectedNodeId = null;
    show(dom.graphEmptyState);
    show(dom.heroBanner);
    switchMainPanel("welcome");
    setGraphReady("图谱已清空");
  }

  function renderGraphPayload(graphPayload, options = {}) {
    if (!window.YojiGraph?.renderGraph) return;
    if (!graphPayload?.nodes?.length) show(dom.graphEmptyState);
    else hide(dom.graphEmptyState);

    window.YojiGraph.renderGraph(graphPayload, {
      focusNodeId: options.focusNodeId || null,
      selectedNodeId: options.selectedNodeId || null,
      preservePositions: !!options.preservePositions
    });
  }

  function normalizeGraphPayload(data, options = {}) {
    const directNodes = data?.nodes || data?.graph?.nodes || [];
    const directEdges = data?.edges || data?.graph?.edges || [];
    if (Array.isArray(directNodes) && directNodes.length) {
      return {
        nodes: directNodes.map(normalizeGraphNode),
        edges: (Array.isArray(directEdges) ? directEdges : []).map(normalizeGraphEdge)
      };
    }

    const arr =
      data?.results ||
      data?.items ||
      data?.data ||
      data?.anime ||
      data?.characters ||
      data?.voice_actors ||
      data?.voiceActors ||
      [];

    if (Array.isArray(arr) && arr.length) {
      return {
        nodes: arr.map((item, index) => {
          const type = normalizeType(item.type || options.fallbackType || "Node");
          const id = item.id || item.raw_id || item.anime_id || `${type}-${index}`;
          const label =
            item.name_cn || item.title_cn || item.display_name_cn || item.name || item.title || id;
          return {
            data: {
              ...item,
              id,
              type,
              label
            }
          };
        }),
        edges: []
      };
    }

    const maybeNode = data?.node || data?.detail;
    if (maybeNode && typeof maybeNode === "object") {
      const type = normalizeType(maybeNode.type || options.fallbackType || "Node");
      const id = maybeNode.id || maybeNode.raw_id || maybeNode.anime_id || type;
      const label =
        maybeNode.name_cn ||
        maybeNode.title_cn ||
        maybeNode.display_name_cn ||
        maybeNode.name ||
        maybeNode.title ||
        id;
      return {
        nodes: [{ data: { ...maybeNode, id, type, label } }],
        edges: []
      };
    }

    return { nodes: [], edges: [] };
  }

  function normalizeGraphNode(node) {
    const data = node?.data ? node.data : node;
    return {
      data: {
        ...data,
        id: data?.id,
        type: normalizeType(data?.type || "Node"),
        label:
          data?.label ||
          data?.name_cn ||
          data?.title_cn ||
          data?.display_name_cn ||
          data?.name ||
          data?.title ||
          data?.id
      }
    };
  }

  function normalizeGraphEdge(edge) {
    const data = edge?.data ? edge.data : edge;
    return {
      data: {
        ...data,
        id:
          data?.id ||
          `${String(data?.source)}::${String(data?.type || data?.relation || "RELATED")}::${String(data?.target)}`
      }
    };
  }

  function firstGraphNode(graphPayload) {
    const node = graphPayload?.nodes?.[0];
    return node?.data ? node.data : node || null;
  }

  function mergeGraphPayload(base, incoming) {
    const nodeMap = new Map();
    const edgeMap = new Map();

    [...(base?.nodes || []), ...(incoming?.nodes || [])].forEach((node) => {
      const n = node?.data ? node.data : node;
      if (!n?.id) return;
      nodeMap.set(String(n.id), normalizeGraphNode(node));
    });

    [...(base?.edges || []), ...(incoming?.edges || [])].forEach((edge) => {
      const e = edge?.data ? edge.data : edge;
      const id =
        e?.id ||
        `${String(e?.source)}::${String(e?.type || e?.relation || "RELATED")}::${String(e?.target)}`;
      edgeMap.set(String(id), normalizeGraphEdge(edge));
    });

    return {
      nodes: Array.from(nodeMap.values()),
      edges: Array.from(edgeMap.values())
    };
  }

  function setGraphLoading(loading) {
    if (loading) show(dom.graphLoading);
    else hide(dom.graphLoading);
  }

  function setGraphReady(text) {
    if (dom.graphStatus) dom.graphStatus.textContent = text;
  }

  function zoomGraph(multiplier) {
    const cy = window.YojiGraph?.getCy?.();
    if (!cy) return;
    const current = cy.zoom();
    const next = current * multiplier;
    cy.zoom({
      level: next,
      renderedPosition: {
        x: cy.width() / 2,
        y: cy.height() / 2
      }
    });
  }

  function showInlineMessage(el, text) {
    if (!el) return;
    el.textContent = text;
  }

  function clearAutocomplete() {
    if (dom.autocompleteAnimeGroup) dom.autocompleteAnimeGroup.innerHTML = "";
    if (dom.autocompleteCharacterGroup) dom.autocompleteCharacterGroup.innerHTML = "";
    if (dom.autocompleteVAGroup) dom.autocompleteVAGroup.innerHTML = "";
  }

  function show(el) {
    el?.classList.remove("hidden");
  }

  function hide(el) {
    el?.classList.add("hidden");
  }

  function pickText(...values) {
    for (const value of values) {
      if (value == null) continue;
      const text = String(value).trim();
      if (text) return text;
    }
    return "";
  }

  function normalizeType(type) {
    const raw = String(type || "").trim().toLowerCase();
    if (raw === "anime") return "Anime";
    if (raw === "character") return "Character";
    if (raw === "voiceactor" || raw === "voice_actor" || raw === "voice actor" || raw === "va")
      return "VoiceActor";
    if (raw === "studio") return "Studio";
    if (raw === "country") return "Country";
    if (raw === "tag") return "Tag";
    if (raw === "node") return "Node";
    return type || "Node";
  }

  function inferAutocompleteType(label) {
    if (label === "Anime") return "Anime";
    if (label === "Character") return "Character";
    if (label === "Voice Actor") return "VoiceActor";
    return "Node";
  }
})();
(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);

  const dom = {
    // detail
    detailNodeTypeBadge: $("#detailNodeTypeBadge"),
    detailFocusBadge: $("#detailFocusBadge"),
    detailMainTitle: $("#detailMainTitle"),
    detailSubTitle: $("#detailSubTitle"),
    badgeScore: $("#detailScoreChip"),
    badgeRank: $("#detailRankChip"),
    badgeDate: $("#detailYearChip"),
    badgeType: null,
    detailSummary: $("#detailSummary"),
    detailCover: $("#detailCover"),
    detailCoverPlaceholder: $("#detailCoverPlaceholder"),
    detailStudios: $("#detailStudios"),
    detailTags: $("#detailTags"),
    detailCharacters: $("#detailCharacters"),
    detailVoiceActors: $("#detailVoiceActors"),
    detailCountries: $("#detailCountries"),
    relationsList: $("#relationsList"),
    askContextText: $("#askContextChip"),

    // lite
    liteNodeTypeBadge: $("#liteNodeTypeBadge"),
    liteFocusBadge: $("#liteFocusBadge"),
    liteNodeType: $("#liteNodeType"),
    liteNodeTitle: $("#liteNodeTitle"),
    liteNodeSubtitle: $("#liteNodeSubtitle"),
    liteAttributes: $("#liteAttributes"),
    liteConnections: $("#liteConnections"),

    // recommend
    recommendationList: $("#recommendationList"),

    // favorites
    favoriteCountText: $("#favoriteCountText"),
    favoriteAnimeList: $("#favoriteAnimeList"),
    favoriteCharacterList: $("#favoriteCharacterList"),
    favoriteVoiceActorList: $("#favoriteVoiceActorList")
  };

  window.YojiPanel = {
    renderAnimeDetail,
    renderLiteDetail,
    renderRecommendations,
    renderFavorites
  };

  function renderAnimeDetail(node, extras = {}, appState = {}) {
    if (!node) return;

    const detail = extras.detail || {};
    const cover = extras.cover || {};
    const relations = extras.relations || {};

    const displayTitle =
      pick(
        detail.name_cn,
        detail.title_cn,
        detail.display_name_cn,
        detail.name,
        detail.title,
        node.name_cn,
        node.title_cn,
        node.name,
        node.title,
        node.label,
        node.id
      ) || "—";

    const subTitle =
      pick(
        detail.name,
        detail.title,
        detail.original_name,
        detail.name_jp,
        node.name,
        node.title,
        node.original_name
      ) || "—";

    const summary =
      pick(
        detail.summary,
        detail.description,
        detail.synopsis,
        detail.introduction,
        node.summary,
        node.description
      ) || "—";

    const studios = normalizeList(
      detail.studios || detail.studio || detail.production || detail.produced_by
    );

    const tags = normalizeList(
      detail.tags || detail.tag_list || detail.genres || detail.themes
    );

    const characters = normalizeList(
      detail.characters || detail.character_list || detail.cast
    );

    const voiceActors = normalizeList(
      detail.voice_actors || detail.voiceActors || detail.cv || detail.seiyuu
    );

    const countries = normalizeList(
      detail.countries || detail.country || detail.regions
    );

    const score = pick(detail.score, detail.rating, node.score);
    const rank = pick(detail.rank, detail.ranking, node.rank);

    const date = pick(
      detail.year,
      detail.air_year,
      detail.release_year,
      detail.date,
      detail.aired,
      node.year
    );

    const type = pick(
      detail.type,
      detail.format,
      detail.media_type,
      node.type_display,
      "Anime"
    );

    setText(dom.detailNodeTypeBadge, "Anime");
    setHidden(dom.detailFocusBadge, !isFocused(node, extras, appState));
    setText(dom.detailMainTitle, displayTitle);
    setText(dom.detailSubTitle, subTitle);
    setText(dom.badgeScore, `Score: ${safeText(score, "-")}`);
    setText(dom.badgeRank, `Rank: ${safeText(rank, "-")}`);
    setText(dom.badgeDate, `Year: ${safeText(date, "-")}`);
    setText(dom.badgeType, `Type: ${safeText(type, "-")}`);
    setText(dom.detailSummary, summary);

    renderCover(cover);
    renderChipList(dom.detailStudios, studios, "studio");
    renderChipList(dom.detailTags, tags, "tag");
    renderListBox(dom.detailCharacters, characters);
    renderListBox(dom.detailVoiceActors, voiceActors);
    renderChipList(dom.detailCountries, countries, "country");
    renderRelations(relations, node, appState);

    if (dom.askContextText) {
      dom.askContextText.textContent = displayTitle;
    }
  }

  function renderLiteDetail(node, extras = {}, appState = {}) {
    if (!node) return;

    const type = normalizeNodeType(node.type || node.label || "Node");

    const title =
      pick(
        node.name_cn,
        node.title_cn,
        node.display_name_cn,
        node.name,
        node.title,
        node.label,
        node.id
      ) || "—";

    const subtitle =
      pick(
        node.name,
        node.title,
        node.original_name,
        node.name_jp,
        node.name_cn !== node.name ? node.name : null
      ) || "—";

    setText(dom.liteNodeTypeBadge, type);
    setHidden(dom.liteFocusBadge, !isFocused(node, extras, appState));
    setText(dom.liteNodeType, type);
    setText(dom.liteNodeTitle, title);
    setText(dom.liteNodeSubtitle, subtitle);

    renderLiteAttributes(node);
    renderLiteConnections(node, extras.graph);
  }

  function renderRecommendations(data, appState = {}) {
    if (!dom.recommendationList) return;

    const items =
      data?.recommendations ||
      data?.items ||
      data?.results ||
      data?.data ||
      [];

    dom.recommendationList.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      dom.recommendationList.appendChild(
        createEmptyCard("No recommendations available.")
      );
      return;
    }

    items.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "recommend-card";

      const title = document.createElement("div");
      title.style.fontWeight = "700";
      title.style.fontSize = "0.98rem";
      title.style.marginBottom = "6px";
      title.textContent =
        pick(
          item.name_cn,
          item.title_cn,
          item.display_name_cn,
          item.name,
          item.title,
          item.label,
          item.id
        ) || `Result ${index + 1}`;

      const meta = document.createElement("div");
      meta.className = "muted-text";
      meta.style.fontSize = "0.82rem";
      meta.textContent = buildRecommendMeta(item);

      card.appendChild(title);
      card.appendChild(meta);

      card.addEventListener("click", () => {
        if (typeof appState.onRecommendationClick === "function") {
          appState.onRecommendationClick(item);
        }
      });

      dom.recommendationList.appendChild(card);
    });
  }

  function renderFavorites(data = {}) {
    const anime = data.anime || [];
    const characters = data.characters || data.character || [];
    const voiceActors = data.voice_actors || data.voiceActors || data.va || [];

    if (dom.favoriteCountText) {
      const total = anime.length + characters.length + voiceActors.length;
      dom.favoriteCountText.textContent = `${total}`;
    }

    renderFavoriteGroup(dom.favoriteAnimeList, anime, "Anime");
    renderFavoriteGroup(dom.favoriteCharacterList, characters, "Character");
    renderFavoriteGroup(dom.favoriteVoiceActorList, voiceActors, "VoiceActor");
  }

  function renderFavoriteGroup(container, items, type) {
    if (!container) return;

    container.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      container.appendChild(createEmptyCard(`No ${type} favorites yet.`));
      return;
    }

    items.forEach((item) => {
      const card = document.createElement("div");
      card.className = "favorite-item";

      const title = document.createElement("div");
      title.style.fontWeight = "600";
      title.textContent =
        pick(
          item.name_cn,
          item.title_cn,
          item.display_name_cn,
          item.name,
          item.title,
          item.label,
          item.raw_id,
          item.item_raw_id
        ) || "—";

      const meta = document.createElement("div");
      meta.className = "muted-text";
      meta.style.fontSize = "0.8rem";
      meta.textContent =
        pick(
          item.type,
          item.item_type,
          type
        ) || type;

      card.appendChild(title);
      card.appendChild(meta);
      container.appendChild(card);
    });
  }

  function renderRelations(relations, node, appState = {}) {
    if (!dom.relationsList) return;

    const items =
      relations?.relations ||
      relations?.items ||
      relations?.results ||
      relations?.data ||
      [];

    dom.relationsList.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      dom.relationsList.appendChild(createEmptyCard("No series relations."));
      return;
    }

    items.forEach((item) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";

      const name =
        pick(
          item.name_cn,
          item.title_cn,
          item.display_name_cn,
          item.name,
          item.title,
          item.label,
          item.id
        ) || "Unknown";

      const relationType =
        pick(
          item.relation_type,
          item.rel_type,
          item.type,
          item.relation
        ) || "Relation";

      chip.textContent = `${relationType}: ${name}`;

      chip.addEventListener("click", () => {
        if (typeof appState.onRelationClick === "function") {
          appState.onRelationClick(item, node);
        }
      });

      dom.relationsList.appendChild(chip);
    });
  }

  function renderLiteAttributes(node) {
    if (!dom.liteAttributes) return;

    dom.liteAttributes.innerHTML = "";

    const ignored = new Set([
      "id",
      "name",
      "name_cn",
      "title",
      "title_cn",
      "label",
      "type"
    ]);

    const entries = Object.entries(node || {}).filter(([key, value]) => {
      if (ignored.has(key)) return false;
      if (value == null) return false;
      if (String(value).trim() === "") return false;
      return true;
    });

    if (entries.length === 0) {
      dom.liteAttributes.appendChild(createEmptyCard("No attributes."));
      return;
    }

    entries.forEach(([key, value]) => {
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.textContent = `${key}: ${formatValue(value)}`;
      dom.liteAttributes.appendChild(chip);
    });
  }

  function renderLiteConnections(node, graph) {
    if (!dom.liteConnections) return;

    dom.liteConnections.innerHTML = "";

    const edges = Array.isArray(graph?.edges) ? graph.edges : [];
    const nodeId = String(node?.id || "");

    const related = edges.filter((edge) => {
      const e = edge?.data ? edge.data : edge;
      return String(e.source) === nodeId || String(e.target) === nodeId;
    });

    if (related.length === 0) {
      dom.liteConnections.appendChild(createEmptyCard("No related connections."));
      return;
    }

    related.forEach((edge) => {
      const e = edge?.data ? edge.data : edge;
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.textContent = `${e.type || e.relation || "RELATED"} · ${
        String(e.source) === nodeId ? e.target : e.source
      }`;
      dom.liteConnections.appendChild(chip);
    });
  }

  function renderCover(cover) {
    if (!dom.detailCover || !dom.detailCoverPlaceholder) return;

    const src =
      pick(
        cover.cover,
        cover.image,
        cover.img,
        cover.url,
        cover.cover_url
      ) || "";

    if (src) {
      dom.detailCover.src = src;
      dom.detailCover.style.display = "block";
      dom.detailCoverPlaceholder.style.display = "none";
    } else {
      dom.detailCover.removeAttribute("src");
      dom.detailCover.style.display = "none";
      dom.detailCoverPlaceholder.style.display = "grid";
    }
  }

  function renderChipList(container, items, type = "") {
    if (!container) return;

    container.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      container.appendChild(createEmptyChip("—"));
      return;
    }

    items.forEach((item) => {
      const chip = document.createElement("div");
      chip.className = "chip";

      if (type) {
        chip.dataset.type = type;
      }

      chip.textContent =
        typeof item === "object"
          ? pick(
              item.name_cn,
              item.title_cn,
              item.display_name_cn,
              item.name,
              item.title,
              item.label,
              item.id
            ) || "—"
          : String(item);

      container.appendChild(chip);
    });
  }

  function renderListBox(container, items) {
    if (!container) return;

    container.innerHTML = "";

    if (!Array.isArray(items) || items.length === 0) {
      container.appendChild(createEmptyChip("—"));
      return;
    }

    items.forEach((item) => {
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.textContent =
        typeof item === "object"
          ? pick(
              item.name_cn,
              item.title_cn,
              item.display_name_cn,
              item.name,
              item.title,
              item.label,
              item.id
            ) || "—"
          : String(item);

      container.appendChild(chip);
    });
  }

  function createEmptyCard(text) {
    const div = document.createElement("div");
    div.className = "muted-text";
    div.textContent = text;
    return div;
  }

  function createEmptyChip(text) {
    const div = document.createElement("div");
    div.className = "chip";
    div.textContent = text;
    return div;
  }

  function setText(el, value) {
    if (!el) return;
    el.textContent = value == null || value === "" ? "—" : String(value);
  }

  function setHidden(el, hidden) {
    if (!el) return;
    el.classList.toggle("hidden", !!hidden);
  }

  function safeText(value, fallback = "—") {
    if (value == null) return fallback;
    const text = String(value).trim();
    return text ? text : fallback;
  }

  function pick(...values) {
    for (const value of values) {
      if (value == null) continue;
      if (typeof value === "string" && value.trim() === "") continue;
      return value;
    }
    return null;
  }

  function normalizeList(value) {
    if (Array.isArray(value)) return value;
    if (value == null) return [];
    if (typeof value === "string") {
      return value
        .split(/[,/|、]+/)
        .map((v) => v.trim())
        .filter(Boolean);
    }
    return [value];
  }

  function normalizeNodeType(type) {
    const raw = String(type || "").trim().toLowerCase();

    if (raw === "anime") return "Anime";
    if (raw === "character") return "Character";
    if (raw === "voiceactor" || raw === "voice_actor" || raw === "va") {
      return "VoiceActor";
    }
    if (raw === "studio") return "Studio";
    if (raw === "country") return "Country";
    if (raw === "tag") return "Tag";

    return type || "Node";
  }

  function isFocused(node, extras = {}, appState = {}) {
    const focusId =
      appState.focusNodeId ||
      extras.focusNodeId ||
      appState.currentNodeId ||
      null;

    if (!focusId) return false;
    return String(node?.id || "") === String(focusId);
  }

  function buildRecommendMeta(item) {
    const score = pick(item.score, item.rating);
    const rank = pick(item.rank, item.ranking);
    const reason = pick(item.reason, item.explanation);

    const parts = [];

    if (score != null) parts.push(`Score ${score}`);
    if (rank != null) parts.push(`Rank ${rank}`);
    if (reason) parts.push(String(reason));

    return parts.join(" · ") || "Recommendation";
  }

  function formatValue(value) {
    if (Array.isArray(value)) {
      return value.map((v) => String(v)).join(", ");
    }
    if (typeof value === "object") {
      try {
        return JSON.stringify(value);
      } catch (err) {
        return String(value);
      }
    }
    return String(value);
  }
})();
(() => {
  "use strict";

  const API_BASE = "";
  const TOKEN_KEY = "yoji_auth_token";
  const USER_KEY = "yoji_auth_user";

  function buildQuery(params = {}) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      if (typeof value === "string" && value.trim() === "") return;
      search.append(key, value);
    });
    const qs = search.toString();
    return qs ? `?${qs}` : "";
  }

  function getToken() {
    try {
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch {
      return "";
    }
  }

  function setAuth(token, user = null) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);

      if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
      else localStorage.removeItem(USER_KEY);
    } catch {}
  }

  function getAuthHeaders(extraHeaders = {}) {
    const token = getToken();
    return {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...extraHeaders
    };
  }

  async function request(path, options = {}) {
    const headers = getAuthHeaders(options.headers || {});
    const response = await fetch(`${API_BASE}${path}`, {
      credentials: "same-origin",
      ...options,
      headers
    });

    const contentType = response.headers.get("content-type") || "";
    let payload = null;

    if (contentType.includes("application/json")) {
      payload = await response.json();
    } else {
      const text = await response.text();
      payload = text ? { raw: text } : {};
    }

    if (!response.ok) {
      const message =
        (payload && (payload.error || payload.message || payload.detail)) ||
        `Request failed: ${response.status}`;
      throw new Error(message);
    }

    return payload;
  }

  async function get(path, params = {}) {
    return request(`${path}${buildQuery(params)}`, { method: "GET" });
  }

  async function post(path, body = {}) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
  }

  async function del(path) {
    return request(path, { method: "DELETE" });
  }

  async function postForm(path, formData) {
    return request(path, {
      method: "POST",
      body: formData
    });
  }

  async function consumeAskStream(body = {}) {
    const response = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders()
      },
      body: JSON.stringify(body || {})
    });

    if (!response.ok) {
      let payload = {};
      try {
        payload = await response.json();
      } catch {}
      throw new Error(
        payload.error || payload.message || `Request failed: ${response.status}`
      );
    }

    if (!response.body) {
      throw new Error("AI stream unavailable.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let answer = "";
    let source = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const line = part
          .split("\n")
          .find((x) => x.trim().startsWith("data:"));
        if (!line) continue;

        const raw = line.replace(/^data:\s*/, "").trim();
        if (!raw) continue;

        try {
          const payload = JSON.parse(raw);
          if (payload.token) answer += payload.token;
          if (payload.source) source = payload.source;
          if (payload.error) throw new Error(payload.error);
        } catch (err) {
          if (err instanceof Error) throw err;
        }
      }
    }

    return {
      answer: answer || "No answer returned.",
      source: source || "general_model"
    };
  }

  function normalizeFavoriteType(type = "") {
    const t = String(type).trim().toLowerCase();
    if (t === "anime") return "Anime";
    if (t === "character") return "Character";
    if (t === "voiceactor" || t === "voice_actor" || t === "voice actor") return "VoiceActor";
    return type || "";
  }

  function normalizeFavoriteName(item = {}) {
    return (
      item.name_cn ||
      item.title_cn ||
      item.name ||
      item.title ||
      item.label ||
      item.display ||
      String(item.id || "")
    );
  }

  const YojiAPI = {
    async searchAnime(q, scope = "all", limit = 30) {
      return get("/search", { query: q, scope, limit, display_lang: "cn" });
    },

    async recommendAnime(id, limit = 12) {
      return get("/recommend", { id, limit });
    },

    async expandNode(nodeId, nodeType = "", limit = 20) {
      return get("/expand", {
        id: nodeId,
        type: nodeType,
        limit,
        display_lang: "cn"
      });
    },

    async autocomplete(q, scope = "all", limit = 8) {
      const items = await get("/autocomplete", { q, scope, limit });
      return {
        anime: Array.isArray(items)
          ? items.map((item) => ({ ...item, type: "Anime" }))
          : [],
        character: [],
        va: []
      };
    },

    async searchCharacter(name, limit = 12) {
      return get("/character", { name, limit, display_lang: "cn" });
    },

    async searchCasting(name, limit = 10) {
      return get("/casting", {
        tags: name,
        limit,
        per_va_limit: 10,
        display_lang: "cn"
      });
    },

    async searchStudio(name, limit = 12) {
      return get("/studio", { name, limit, display_lang: "cn" });
    },

    async discoverNiche(pop = 2000, rich = 8, limit = 12) {
      return get("/niche", {
        pop,
        rich,
        limit,
        display_lang: "cn"
      });
    },

    async askAI(question, context = {}) {
      return consumeAskStream({
        question,
        anime_id: context.anime_id,
        node_id: context.node_id,
        node_type: context.node_type
      });
    },

    async identifyAnime(file) {
      const form = new FormData();
      form.append("image", file);
      return postForm("/identify", form);
    },

    async login(username, password) {
      const data = await post("/auth/login", {
        email: String(username || "").trim(),
        password: password || ""
      });

      if (data?.token) setAuth(data.token, data.user || null);
      return data;
    },

    async register(username, password) {
      const email = String(username || "").trim();
      const displayName = email.includes("@") ? email.split("@")[0] : email;

      const data = await post("/auth/register", {
        email,
        password: password || "",
        display_name: displayName || "user"
      });

      if (data?.token) setAuth(data.token, data.user || null);
      return data;
    },

    async logout() {
      setAuth("", null);
      return { message: "logged out" };
    },

    async getFavorites() {
      if (!getToken()) {
        return {
          favorite_limit: 10,
          favorite_count: 0,
          anime: [],
          characters: [],
          voice_actors: []
        };
      }

      const data = await get("/favorites");
      const grouped = data?.favorites || {};

      return {
        favorite_limit: data?.favorite_limit ?? 10,
        favorite_count: data?.favorite_count ?? 0,
        anime: grouped.Anime || [],
        characters: grouped.Character || [],
        voice_actors: grouped.VoiceActor || []
      };
    },

    async addFavorite(item) {
      if (!getToken()) {
        throw new Error("Please log in first.");
      }

      return post("/favorites", {
        item_type: normalizeFavoriteType(item?.type),
        item_raw_id: item?.id,
        item_display_name: normalizeFavoriteName(item)
      });
    },

    async removeFavorite(item) {
      if (!getToken()) {
        throw new Error("Please log in first.");
      }

      if (item?.favorite_id) {
        return del(`/favorites/${encodeURIComponent(item.favorite_id)}`);
      }

      const favorites = await this.getFavorites();
      const all = [
        ...(favorites.anime || []),
        ...(favorites.characters || []),
        ...(favorites.voice_actors || [])
      ];

      const matched = all.find((fav) => {
        return (
          String(fav.item_raw_id) === String(item?.id) &&
          normalizeFavoriteType(fav.item_type) === normalizeFavoriteType(item?.type)
        );
      });

      if (!matched?.favorite_id) {
        throw new Error("Favorite not found.");
      }

      return del(`/favorites/${encodeURIComponent(matched.favorite_id)}`);
    },

    async getHistory() {
      try {
        const raw = localStorage.getItem("yoji_local_history");
        return raw ? JSON.parse(raw) : [];
      } catch {
        return [];
      }
    },

    async addHistory(item) {
      try {
        const current = await this.getHistory();
        const merged = [
          item,
          ...current.filter(
            (x) => !(String(x.id) === String(item.id) && String(x.type) === String(item.type))
          )
        ].slice(0, 20);
        localStorage.setItem("yoji_local_history", JSON.stringify(merged));
        return { items: merged };
      } catch {
        return { items: [] };
      }
    }
  };

  window.YojiAPI = YojiAPI;
})();
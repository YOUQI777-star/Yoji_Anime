(() => {
  "use strict";

  let cy = null;

  const state = {
    focusNodeId: null,
    selectedNodeId: null,
    lastTapNodeId: null,
    lastTapTime: 0,
    lastLayoutName: "cose"
  };

  const DEFAULTS = {
    doubleTapThreshold: 280,
    animationDuration: 320
  };

  const bridge = {
    container: null,
    handlers: {
      onNodeClick: null,
      onNodeDoubleClick: null,
      onCanvasClick: null
    }
  };

  window.YojiGraph = {
    init,
    renderGraph,
    clearGraph,
    fit,
    resetView,
    setVisualCenter,
    highlightNode,
    getCy: () => cy
  };

  function init(container, handlers = {}) {
    if (!container) {
      console.error("YojiGraph.init: container not found");
      return;
    }

    bridge.container = container;
    bridge.handlers = {
      onNodeClick: handlers.onNodeClick || null,
      onNodeDoubleClick: handlers.onNodeDoubleClick || null,
      onCanvasClick: handlers.onCanvasClick || null
    };

    cy = cytoscape({
      container,
      elements: [],
      minZoom: 0.22,
      maxZoom: 2.4,
      wheelSensitivity: 0.18,
      motionBlur: true,
      selectionType: "single",
      textureOnViewport: true,
      style: buildStyles(),
      layout: {
        name: "preset"
      }
    });

    bindCyEvents();
  }

  function buildStyles() {
    return [
      {
        selector: "node",
        style: {
          "background-color": "data(nodeColor)",
          "border-width": "mapData(borderWeight, 1, 4, 1.4, 3.6)",
          "border-color": "data(borderColor)",
          "label": "data(label)",
          "font-size": "mapData(labelLevel, 1, 4, 11, 34)",
          "font-weight": "mapData(fontWeight, 400, 700, 400, 700)",
          "color": "data(textColor)",
          "text-wrap": "wrap",
          "text-max-width": "data(textMaxWidth)",
          "text-valign": "center",
          "text-halign": "center",
          "text-outline-width": "data(textOutlineWidth)",
          "text-outline-color": "data(textOutlineColor)",
          "width": "mapData(sizeLevel, 1, 4, 28, 110)",
          "height": "mapData(sizeLevel, 1, 4, 28, 110)",
          "overlay-padding": 8,
          "overlay-opacity": 0,
          "z-index-compare": "manual",
          "z-index": "mapData(zLevel, 1, 10, 1, 10)",
          "transition-property":
            "background-color, border-color, width, height, font-size, color, text-outline-width, opacity",
          "transition-duration": `${DEFAULTS.animationDuration}ms`
        }
      },
      {
        selector: "node[type = 'Anime']",
        style: {
          shape: "round-rectangle"
        }
      },
      {
        selector: "node[type = 'Character']",
        style: {
          shape: "ellipse"
        }
      },
      {
        selector: "node[type = 'VoiceActor']",
        style: {
          shape: "ellipse"
        }
      },
      {
        selector: "node[type = 'Studio']",
        style: {
          shape: "round-rectangle"
        }
      },
      {
        selector: "node[type = 'Country']",
        style: {
          shape: "round-rectangle"
        }
      },
      {
        selector: "node[type = 'Tag']",
        style: {
          shape: "diamond"
        }
      },
      {
        selector: "node.focused",
        style: {
          "border-width": 4.4,
          "border-color": "#ff3b30",
          "shadow-blur": 32,
          "shadow-color": "#c91f1f",
          "shadow-opacity": 0.35,
          "shadow-offset-x": 0,
          "shadow-offset-y": 0,
          "z-index": 999
        }
      },
      {
        selector: "node.selected",
        style: {
          "border-width": 3.4,
          "border-color": "#e12727",
          "shadow-blur": 18,
          "shadow-color": "#e12727",
          "shadow-opacity": 0.2,
          "shadow-offset-x": 0,
          "shadow-offset-y": 0
        }
      },
      {
        selector: "node.deemphasized",
        style: {
          opacity: 0.55
        }
      },
      {
        selector: "edge",
        style: {
          "curve-style": "bezier",
          "line-color": "data(lineColor)",
          "target-arrow-color": "data(lineColor)",
          "target-arrow-shape": "triangle",
          "arrow-scale": 0.72,
          "width": "mapData(edgeWeight, 1, 4, 1, 3)",
          "opacity": 0.74,
          "z-index-compare": "manual",
          "z-index": 0,
          "transition-property": "line-color, width, opacity",
          "transition-duration": `${DEFAULTS.animationDuration}ms`
        }
      },
      {
        selector: "edge.related-main",
        style: {
          "line-color": "#cf2a2a",
          "target-arrow-color": "#cf2a2a"
        }
      },
      {
        selector: "edge.related-extra",
        style: {
          "line-color": "#8e2b2b",
          "target-arrow-color": "#8e2b2b"
        }
      },
      {
        selector: "edge.related-skip",
        style: {
          "line-color": "#6d6d6d",
          "target-arrow-color": "#6d6d6d"
        }
      },
      {
        selector: "edge.related-alt",
        style: {
          "line-color": "#9a9a9a",
          "target-arrow-color": "#9a9a9a"
        }
      },
      {
        selector: "edge.related-universe",
        style: {
          "line-color": "#c0c0c0",
          "target-arrow-color": "#c0c0c0"
        }
      },
      {
        selector: "edge.connected-focus",
        style: {
          width: 2.8,
          opacity: 0.95
        }
      },
      {
        selector: "edge.deemphasized",
        style: {
          opacity: 0.18
        }
      }
    ];
  }

  function bindCyEvents() {
    if (!cy) return;

    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      const now = Date.now();
      const nodeId = node.id();

      const isDoubleTap =
        state.lastTapNodeId === nodeId &&
        now - state.lastTapTime <= DEFAULTS.doubleTapThreshold;

      state.lastTapNodeId = nodeId;
      state.lastTapTime = now;

      setSelectedNode(nodeId);

      if (typeof bridge.handlers.onNodeClick === "function") {
        bridge.handlers.onNodeClick(node.data());
      }

      if (isDoubleTap) {
        setVisualCenter(nodeId, { animate: true });

        if (typeof bridge.handlers.onNodeDoubleClick === "function") {
          bridge.handlers.onNodeDoubleClick(node.data());
        }
      }
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        clearSelection();

        if (typeof bridge.handlers.onCanvasClick === "function") {
          bridge.handlers.onCanvasClick();
        }
      }
    });
  }

  function renderGraph(payload, options = {}) {
    if (!cy) return;

    const rawNodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
    const rawEdges = Array.isArray(payload?.edges) ? payload.edges : [];

    const nodes = rawNodes.map(normalizeNode);
    const edges = rawEdges.map(normalizeEdge);

    const normalizedFocusNodeId =
      options.focusNodeId ||
      state.focusNodeId ||
      options.selectedNodeId ||
      nodes[0]?.data?.id ||
      null;

    const normalizedSelectedNodeId =
      options.selectedNodeId ||
      state.selectedNodeId ||
      normalizedFocusNodeId ||
      null;

    state.focusNodeId = normalizedFocusNodeId;
    state.selectedNodeId = normalizedSelectedNodeId;

    const typedNodes = applyVisualLevels(
      nodes,
      edges,
      state.focusNodeId,
      state.selectedNodeId
    );
    const typedEdges = applyEdgeVisualLevels(edges, state.focusNodeId);
    const elements = [...typedNodes, ...typedEdges];

    const preservePositions = !!options.preservePositions && cy.nodes().length > 0;
    const previousPositions = preservePositions ? snapshotPositions() : null;

    cy.elements().remove();
    cy.add(elements);

    if (preservePositions && previousPositions) {
      restorePositions(previousPositions);
      runLayout("preset", { animate: false });
    } else {
      runLayout("cose", {
        animate: true,
        fit: true
      });
    }

    applySelectionClasses();
    applyFocusClasses();

    if (state.focusNodeId) {
      centerOnNode(state.focusNodeId, { animate: true, zoom: null });
    }
  }

  function normalizeNode(raw) {
    const data = raw?.data ? { ...raw.data } : { ...raw };

    const nodeId = data.id || data.node_id || data.uuid || data.name;
    const nodeType = normalizeType(data.type || data.label || "Node");
    const label =
      data.label ||
      data.display_name ||
      data.name ||
      data.title ||
      data.name_cn ||
      data.title_cn ||
      nodeId;

    return {
      data: {
        ...data,
        id: String(nodeId),
        type: nodeType,
        label,
        nodeColor: inferNodeColor(nodeType),
        borderColor: inferNodeBorderColor(nodeType),
        textColor: inferTextColor(nodeType),
        textOutlineColor: inferTextOutline(nodeType),
        textOutlineWidth: 0,
        textMaxWidth: 140,
        sizeLevel: 2,
        labelLevel: 2,
        borderWeight: 1.8,
        zLevel: 2,
        fontWeight: 500
      }
    };
  }

  function normalizeEdge(raw) {
    const data = raw?.data ? { ...raw.data } : { ...raw };

    const source = String(data.source);
    const target = String(data.target);
    const type = data.type || data.relation || data.rel_type || "RELATED";
    const id = data.id || `${source}::${type}::${target}`;
    const relationGroup = normalizeRelationGroup(
      data.group || data.relation_group || ""
    );

    return {
      data: {
        ...data,
        id: String(id),
        source,
        target,
        type,
        group: relationGroup,
        lineColor: inferEdgeColor(relationGroup, type),
        edgeWeight: inferEdgeWeight(type, relationGroup)
      },
      classes: buildEdgeClasses(relationGroup)
    };
  }

  function normalizeType(type) {
    const t = String(type || "").trim().toLowerCase();

    if (t === "anime") return "Anime";
    if (t === "character") return "Character";
    if (t === "voiceactor" || t === "voice_actor" || t === "va") {
      return "VoiceActor";
    }
    if (t === "studio") return "Studio";
    if (t === "country") return "Country";
    if (t === "tag") return "Tag";

    return String(type || "Node");
  }

  function normalizeRelationGroup(group) {
    const g = String(group || "").trim().toLowerCase();

    if (["main", "extra", "skip", "alt", "universe"].includes(g)) {
      return g;
    }

    return "";
  }

  function inferNodeColor(type) {
    switch (type) {
      case "Anime":
        return "#b71c1c";
      case "Character":
        return "#8f1111";
      case "VoiceActor":
        return "#c8c8c8";
      case "Studio":
        return "#666666";
      case "Country":
        return "#d8d8d8";
      case "Tag":
        return "#2c2c2c";
      default:
        return "#444444";
    }
  }

  function inferNodeBorderColor(type) {
    switch (type) {
      case "Anime":
        return "#ea3c3c";
      case "Character":
        return "#d73333";
      case "VoiceActor":
        return "#8b8b8b";
      case "Studio":
        return "#8f8f8f";
      case "Country":
        return "#a8a8a8";
      case "Tag":
        return "#6e6e6e";
      default:
        return "#7a7a7a";
    }
  }

  function inferTextColor(type) {
    switch (type) {
      case "VoiceActor":
      case "Country":
        return "#111111";
      default:
        return "#f5f5f5";
    }
  }

  function inferTextOutline(type) {
    switch (type) {
      case "VoiceActor":
      case "Country":
        return "rgba(255,255,255,0.0)";
      default:
        return "rgba(0,0,0,0.22)";
    }
  }

  function inferEdgeColor(group, type) {
    if (group === "main") return "#cf2a2a";
    if (group === "extra") return "#8e2b2b";
    if (group === "skip") return "#6d6d6d";
    if (group === "alt") return "#9a9a9a";
    if (group === "universe") return "#c0c0c0";

    const upper = String(type || "").toUpperCase();

    if (upper.includes("VOICED")) return "#7f7f7f";
    if (upper.includes("HAS_CHARACTER")) return "#8f1111";
    if (upper.includes("HAS_TAG")) return "#595959";
    if (upper.includes("PRODUCED") || upper.includes("STUDIO")) return "#7a7a7a";

    return "#666666";
  }

  function inferEdgeWeight(type, group) {
    if (group === "main") return 4;
    if (group === "extra") return 3;
    if (group === "skip" || group === "alt" || group === "universe") return 2;

    const upper = String(type || "").toUpperCase();

    if (upper.includes("RELATED")) return 3;
    if (upper.includes("HAS_CHARACTER")) return 2.5;

    return 1.8;
  }

  function buildEdgeClasses(group) {
    if (!group) return "";
    return `related-${group}`;
  }

  function applyVisualLevels(nodes, edges, focusNodeId, selectedNodeId) {
    const adjacency = buildAdjacency(edges);
    const firstRing = focusNodeId ? adjacency.get(focusNodeId) || new Set() : new Set();
    const secondRing = new Set();

    if (focusNodeId) {
      firstRing.forEach((nid) => {
        const neighbors = adjacency.get(nid) || new Set();

        neighbors.forEach((n2) => {
          if (n2 !== focusNodeId && !firstRing.has(n2)) {
            secondRing.add(n2);
          }
        });
      });
    }

    return nodes.map((node) => {
      const data = { ...node.data };
      const id = data.id;
      const typePriority = getTypePriority(data.type);

      let ringLevel = 1;
      if (focusNodeId && id === focusNodeId) ringLevel = 4;
      else if (focusNodeId && firstRing.has(id)) ringLevel = 3;
      else if (focusNodeId && secondRing.has(id)) ringLevel = 2;
      else ringLevel = 1;

      const sizeLevel = clampLevel(ringLevel + typePriority * 0.2);
      const labelLevel = clampLevel(ringLevel + typePriority * 0.18);

      data.sizeLevel = sizeLevel;
      data.labelLevel = labelLevel;
      data.borderWeight =
        ringLevel >= 4 ? 4 : ringLevel >= 3 ? 2.8 : ringLevel >= 2 ? 2.1 : 1.6;
      data.zLevel = ringLevel >= 4 ? 10 : ringLevel >= 3 ? 7 : ringLevel >= 2 ? 5 : 2;
      data.fontWeight = ringLevel >= 4 ? 700 : ringLevel >= 3 ? 650 : 520;
      data.textMaxWidth = ringLevel >= 4 ? 220 : ringLevel >= 3 ? 180 : ringLevel >= 2 ? 140 : 90;
      data.textOutlineWidth = ringLevel >= 3 ? 1.3 : ringLevel >= 2 ? 0.8 : 0.4;

      const classes = [];
      if (selectedNodeId && id === selectedNodeId) classes.push("selected");
      if (focusNodeId && id === focusNodeId) classes.push("focused");
      if (focusNodeId && ringLevel === 1) classes.push("deemphasized");

      return {
        data,
        classes: classes.join(" ")
      };
    });
  }

  function applyEdgeVisualLevels(edges, focusNodeId) {
    return edges.map((edge) => {
      const data = { ...edge.data };
      const classes = [edge.classes].filter(Boolean);

      const touchesFocus =
        focusNodeId &&
        (String(data.source) === String(focusNodeId) ||
          String(data.target) === String(focusNodeId));

      if (touchesFocus) {
        classes.push("connected-focus");
      } else if (focusNodeId) {
        classes.push("deemphasized");
      }

      return {
        data,
        classes: classes.join(" ")
      };
    });
  }

  function buildAdjacency(edges) {
    const map = new Map();

    edges.forEach((edge) => {
      const e = edge?.data ? edge.data : edge;
      const source = String(e.source);
      const target = String(e.target);

      if (!map.has(source)) map.set(source, new Set());
      if (!map.has(target)) map.set(target, new Set());

      map.get(source).add(target);
      map.get(target).add(source);
    });

    return map;
  }

  function getTypePriority(type) {
    switch (type) {
      case "Anime":
        return 1.2;
      case "Character":
        return 1.0;
      case "VoiceActor":
        return 0.8;
      case "Studio":
        return 0.6;
      case "Country":
        return 0.4;
      case "Tag":
        return 0.2;
      default:
        return 0.3;
    }
  }

  function clampLevel(level) {
    return Math.max(1, Math.min(4, level));
  }

  function setSelectedNode(nodeId) {
    state.selectedNodeId = String(nodeId);
    applySelectionClasses();
  }

  function highlightNode(nodeId) {
    if (!cy) return;
    setSelectedNode(nodeId);
  }

  function setVisualCenter(nodeId, options = {}) {
    if (!cy) return;

    state.focusNodeId = String(nodeId);
    applyFocusReweighting();
    applySelectionClasses();
    applyFocusClasses();

    centerOnNode(nodeId, {
      animate: options.animate !== false,
      zoom: options.zoom ?? null
    });
  }

  function applyFocusReweighting() {
    if (!cy) return;

    const currentNodes = cy.nodes().map((n) => ({
      data: { ...n.data() }
    }));

    const currentEdges = cy.edges().map((e) => ({
      data: { ...e.data() },
      classes: e.classes()
    }));

    const nextNodes = applyVisualLevels(
      currentNodes,
      currentEdges,
      state.focusNodeId,
      state.selectedNodeId
    );
    const nextEdges = applyEdgeVisualLevels(currentEdges, state.focusNodeId);

    nextNodes.forEach((node) => {
      const el = cy.getElementById(node.data.id);
      if (el && el.length) {
        Object.entries(node.data).forEach(([key, value]) => {
          el.data(key, value);
        });
        el.classes(node.classes || "");
      }
    });

    nextEdges.forEach((edge) => {
      const el = cy.getElementById(edge.data.id);
      if (el && el.length) {
        Object.entries(edge.data).forEach(([key, value]) => {
          el.data(key, value);
        });
        el.classes(edge.classes || "");
      }
    });
  }

  function applySelectionClasses() {
    if (!cy) return;

    cy.nodes().forEach((node) => {
      node.toggleClass("selected", node.id() === String(state.selectedNodeId || ""));
    });
  }

  function applyFocusClasses() {
    if (!cy) return;

    cy.nodes().forEach((node) => {
      node.toggleClass("focused", node.id() === String(state.focusNodeId || ""));

      if (state.focusNodeId) {
        const isFocused = node.id() === String(state.focusNodeId);
        const isNeighbor = node
          .neighborhood("node")
          .some((n) => n.id() === String(state.focusNodeId));

        node.toggleClass(
          "deemphasized",
          !isFocused &&
            !isNeighbor &&
            node.id() !== String(state.selectedNodeId || "")
        );
      } else {
        node.removeClass("deemphasized");
      }
    });

    cy.edges().forEach((edge) => {
      const touchesFocus =
        state.focusNodeId &&
        (edge.source().id() === String(state.focusNodeId) ||
          edge.target().id() === String(state.focusNodeId));

      edge.toggleClass("connected-focus", !!touchesFocus);
      edge.toggleClass("deemphasized", !!state.focusNodeId && !touchesFocus);
    });
  }

  function centerOnNode(nodeId, options = {}) {
    if (!cy) return;

    const node = cy.getElementById(String(nodeId));
    if (!node || !node.length) return;

    const shouldAnimate = options.animate !== false;
    const targetZoom =
      typeof options.zoom === "number"
        ? options.zoom
        : Math.min(Math.max(cy.zoom(), 0.78), 1.15);

    cy.animate(
      {
        center: {
          eles: node
        },
        zoom: targetZoom
      },
      {
        duration: shouldAnimate ? DEFAULTS.animationDuration : 0,
        easing: "ease-in-out-cubic"
      }
    );
  }

  function runLayout(name = "cose", options = {}) {
    if (!cy) return;

    state.lastLayoutName = name;
    let layoutOptions = {};

    if (name === "cose") {
      layoutOptions = {
        name: "cose",
        animate: options.animate !== false,
        fit: options.fit !== false,
        padding: 36,
        nodeRepulsion: 9000,
        idealEdgeLength: 120,
        edgeElasticity: 120,
        nestingFactor: 0.7,
        gravity: 0.18,
        numIter: 1000,
        randomize: false,
        componentSpacing: 80,
        animationDuration: DEFAULTS.animationDuration
      };
    } else if (name === "preset") {
      layoutOptions = {
        name: "preset",
        fit: options.fit !== false,
        animate: options.animate === true,
        padding: 30
      };
    } else {
      layoutOptions = {
        name,
        animate: options.animate !== false,
        fit: options.fit !== false
      };
    }

    cy.layout(layoutOptions).run();
  }

  function snapshotPositions() {
    if (!cy) return null;

    const map = new Map();
    cy.nodes().forEach((node) => {
      map.set(node.id(), { ...node.position() });
    });

    return map;
  }

  function restorePositions(snapshot) {
    if (!cy || !snapshot) return;

    cy.nodes().forEach((node) => {
      const pos = snapshot.get(node.id());
      if (pos) {
        node.position(pos);
      }
    });
  }

  function fit() {
    if (!cy) return;
    cy.fit(cy.elements(), 36);
  }

  function resetView() {
    if (!cy) return;

    cy.animate(
      {
        fit: {
          eles: cy.elements(),
          padding: 36
        }
      },
      {
        duration: DEFAULTS.animationDuration,
        easing: "ease-in-out-cubic"
      }
    );
  }

  function clearSelection() {
    state.selectedNodeId = null;
    state.focusNodeId = null;
    applySelectionClasses();
    applyFocusClasses();
  }

  function clearGraph() {
    if (!cy) return;

    cy.elements().remove();
    state.focusNodeId = null;
    state.selectedNodeId = null;
    state.lastTapNodeId = null;
    state.lastTapTime = 0;
  }
})();
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import {
    forceSimulation,
    forceLink,
    forceManyBody,
    forceCenter,
    forceCollide,
    type SimulationNodeDatum,
    type SimulationLinkDatum,
  } from "d3-force";
  import { settings } from "../lib/stores/settings";
  import { get } from "svelte/store";
  import { getGraphData, type GraphNode, type GraphEdge } from "../lib/tauri";

  interface SimNode extends SimulationNodeDatum {
    id: string;
    label: string;
    node_type: string;
  }

  interface SimLink extends SimulationLinkDatum<SimNode> {
    edge_type: string;
  }

  // ── Company color palette (configurable) ──
  const COMPANY_PALETTE = [
    "#B4A882",
    "#82A8B4",
    "#B48282",
    "#82B498",
    "#A882B4",
    "#B4A068",
  ];

  let svgEl: SVGSVGElement | undefined = $state(undefined);
  let width = $state(900);
  let height = $state(600);
  let nodes: SimNode[] = $state([]);
  let links: SimLink[] = $state([]);
  let hoveredNode: string | null = $state(null);
  let connectedIds: Set<string> = $state(new Set());
  let simulation: ReturnType<typeof forceSimulation<SimNode>> | null = null;
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Drag state
  let dragNode: SimNode | null = $state(null);
  let isDragging = $state(false);

  // Pan/zoom state
  let panX = $state(0);
  let panY = $state(0);
  let scale = $state(1);
  let isPanning = $state(false);
  let panStart = { x: 0, y: 0, panX: 0, panY: 0 };

  // Company color map — assigned dynamically
  let companyColorMap: Map<string, string> = new Map();

  const NODE_RADIUS: Record<string, number> = {
    meeting: 8,
    person: 6,
    company: 10,
  };

  function getColor(node: SimNode): string {
    if (node.node_type === "meeting") return "#A8A078";
    if (node.node_type === "person") return "#78756E";
    if (node.node_type === "company") {
      return companyColorMap.get(node.id) ?? "#B4A882";
    }
    return "#78756E";
  }

  function getRadius(nodeType: string): number {
    return NODE_RADIUS[nodeType] ?? 6;
  }

  function assignCompanyColors(nodeList: SimNode[]) {
    let idx = 0;
    for (const n of nodeList) {
      if (n.node_type === "company" && !companyColorMap.has(n.id)) {
        companyColorMap.set(n.id, COMPANY_PALETTE[idx % COMPANY_PALETTE.length]);
        idx++;
      }
    }
  }

  function updateSize() {
    if (svgEl) {
      const rect = svgEl.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
    }
  }

  /** Convert client (screen) coords to SVG world coords */
  function clientToWorld(clientX: number, clientY: number): { x: number; y: number } {
    const rect = svgEl!.getBoundingClientRect();
    return {
      x: (clientX - rect.left - panX) / scale,
      y: (clientY - rect.top - panY) / scale,
    };
  }

  function buildConnectedSet(nodeId: string): Set<string> {
    const s = new Set<string>();
    s.add(nodeId);
    for (const l of links) {
      const src = typeof l.source === "object" ? (l.source as SimNode).id : l.source;
      const tgt = typeof l.target === "object" ? (l.target as SimNode).id : l.target;
      if (src === nodeId) s.add(tgt as string);
      if (tgt === nodeId) s.add(src as string);
    }
    return s;
  }

  function handleMouseEnter(node: SimNode) {
    if (isDragging) return;
    hoveredNode = node.id;
    connectedIds = buildConnectedSet(node.id);
  }

  function handleMouseLeave() {
    if (isDragging) return;
    hoveredNode = null;
    connectedIds = new Set();
  }

  function handleClick(node: SimNode) {
    // Don't navigate if we were dragging
    if (isDragging) return;
    if (node.node_type === "meeting") {
      const meetingId = node.id.replace("meeting:", "");
      window.location.hash = `meeting/${meetingId}`;
    } else {
      window.location.hash = "dashboard";
    }
  }

  // ── Node drag handlers ──
  function handleNodePointerDown(e: PointerEvent, node: SimNode) {
    e.stopPropagation();
    e.preventDefault();
    dragNode = node;
    isDragging = false;

    const world = clientToWorld(e.clientX, e.clientY);

    if (simulation) {
      simulation.alphaTarget(0.3).restart();
    }
    node.fx = node.x;
    node.fy = node.y;

    // Store offset between cursor world position and node position
    (dragNode as any)._offsetX = world.x - (node.x ?? 0);
    (dragNode as any)._offsetY = world.y - (node.y ?? 0);

    (e.target as Element).setPointerCapture(e.pointerId);
  }

  function handleNodePointerMove(e: PointerEvent) {
    if (!dragNode || !svgEl) return;
    isDragging = true;
    e.preventDefault();
    e.stopPropagation();

    const world = clientToWorld(e.clientX, e.clientY);
    dragNode.fx = world.x - ((dragNode as any)._offsetX ?? 0);
    dragNode.fy = world.y - ((dragNode as any)._offsetY ?? 0);
  }

  function handleNodePointerUp(e: PointerEvent) {
    if (!dragNode) return;
    e.preventDefault();
    e.stopPropagation();

    dragNode.fx = null;
    dragNode.fy = null;

    if (simulation) {
      simulation.alphaTarget(0);
    }

    // Brief timeout so the click handler can check isDragging
    const wasDragging = isDragging;
    dragNode = null;
    if (wasDragging) {
      setTimeout(() => {
        isDragging = false;
      }, 0);
    } else {
      isDragging = false;
    }
  }

  // ── Background pan handlers ──
  function handleBgPointerDown(e: PointerEvent) {
    // Only pan on primary button on the background itself
    if (e.button !== 0) return;
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY, panX, panY };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    e.preventDefault();
  }

  function handleBgPointerMove(e: PointerEvent) {
    if (!isPanning) return;
    e.preventDefault();
    panX = panStart.panX + (e.clientX - panStart.x);
    panY = panStart.panY + (e.clientY - panStart.y);
  }

  function handleBgPointerUp(e: PointerEvent) {
    if (!isPanning) return;
    isPanning = false;
    e.preventDefault();
  }

  // ── Zoom (mousewheel) ──
  function handleWheel(e: WheelEvent) {
    e.preventDefault();
    const rect = svgEl!.getBoundingClientRect();
    const cursorX = e.clientX - rect.left;
    const cursorY = e.clientY - rect.top;

    const zoomFactor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
    const newScale = Math.min(Math.max(scale * zoomFactor, 0.1), 8);

    // Adjust pan so zoom centers on cursor
    panX = cursorX - (cursorX - panX) * (newScale / scale);
    panY = cursorY - (cursorY - panY) * (newScale / scale);
    scale = newScale;
  }

  function nodeOpacityClass(nodeId: string): string {
    if (!hoveredNode) return "graph-full";
    return connectedIds.has(nodeId) ? "graph-full" : "graph-dimmed";
  }

  function linkOpacityClass(link: SimLink): string {
    if (!hoveredNode) return "graph-link-default";
    const src = typeof link.source === "object" ? (link.source as SimNode).id : link.source;
    const tgt = typeof link.target === "object" ? (link.target as SimNode).id : link.target;
    if (src === hoveredNode || tgt === hoveredNode) return "graph-link-active";
    return "graph-link-dimmed";
  }

  function isLinkActive(link: SimLink): boolean {
    if (!hoveredNode) return false;
    const src = typeof link.source === "object" ? (link.source as SimNode).id : link.source;
    const tgt = typeof link.target === "object" ? (link.target as SimNode).id : link.target;
    return src === hoveredNode || tgt === hoveredNode;
  }

  onMount(async () => {
    updateSize();
    window.addEventListener("resize", updateSize);

    // ── DUMMY DATA (remove before PR) ──
    const DUMMY_GRAPH = true;
    const dummyData = DUMMY_GRAPH ? {
      nodes: [
        { id: "meeting:2026-03-17-project-kickoff-acme", label: "Project Kickoff", node_type: "meeting" },
        { id: "meeting:2026-03-17-weekly-standup", label: "Weekly Standup", node_type: "meeting" },
        { id: "meeting:2026-03-16-quarterly-review", label: "Q1 Review", node_type: "meeting" },
        { id: "meeting:2026-03-16-design-sprint-retro", label: "Design Retro", node_type: "meeting" },
        { id: "meeting:2026-03-15-investor-update", label: "Investor Update", node_type: "meeting" },
        { id: "meeting:2026-03-15-1on1-sarah", label: "1:1 Sarah", node_type: "meeting" },
        { id: "meeting:2026-03-14-product-planning", label: "Product Planning", node_type: "meeting" },
        { id: "person:jane-smith", label: "Jane Smith", node_type: "person" },
        { id: "person:bob-jones", label: "Bob Jones", node_type: "person" },
        { id: "person:alice-chen", label: "Alice Chen", node_type: "person" },
        { id: "person:tim", label: "Tim", node_type: "person" },
        { id: "person:sarah", label: "Sarah", node_type: "person" },
        { id: "person:mike", label: "Mike", node_type: "person" },
        { id: "person:lisa", label: "Lisa", node_type: "person" },
        { id: "person:dave-wilson", label: "Dave Wilson", node_type: "person" },
        { id: "company:acme", label: "Acme Corp", node_type: "company" },
        { id: "company:globex", label: "Globex Inc", node_type: "company" },
        { id: "company:initech", label: "Initech", node_type: "company" },
      ],
      edges: [
        { source: "person:jane-smith", target: "meeting:2026-03-17-project-kickoff-acme", edge_type: "attended" },
        { source: "person:bob-jones", target: "meeting:2026-03-17-project-kickoff-acme", edge_type: "attended" },
        { source: "person:alice-chen", target: "meeting:2026-03-17-project-kickoff-acme", edge_type: "attended" },
        { source: "person:tim", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
        { source: "person:sarah", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
        { source: "person:mike", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
        { source: "person:lisa", target: "meeting:2026-03-17-weekly-standup", edge_type: "attended" },
        { source: "person:jane-smith", target: "meeting:2026-03-16-quarterly-review", edge_type: "attended" },
        { source: "person:bob-jones", target: "meeting:2026-03-16-quarterly-review", edge_type: "attended" },
        { source: "person:tim", target: "meeting:2026-03-16-quarterly-review", edge_type: "attended" },
        { source: "person:sarah", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
        { source: "person:mike", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
        { source: "person:lisa", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
        { source: "person:tim", target: "meeting:2026-03-16-design-sprint-retro", edge_type: "attended" },
        { source: "person:tim", target: "meeting:2026-03-15-investor-update", edge_type: "attended" },
        { source: "person:jane-smith", target: "meeting:2026-03-15-investor-update", edge_type: "attended" },
        { source: "person:dave-wilson", target: "meeting:2026-03-15-investor-update", edge_type: "attended" },
        { source: "person:tim", target: "meeting:2026-03-15-1on1-sarah", edge_type: "attended" },
        { source: "person:sarah", target: "meeting:2026-03-15-1on1-sarah", edge_type: "attended" },
        { source: "person:tim", target: "meeting:2026-03-14-product-planning", edge_type: "attended" },
        { source: "person:mike", target: "meeting:2026-03-14-product-planning", edge_type: "attended" },
        { source: "person:lisa", target: "meeting:2026-03-14-product-planning", edge_type: "attended" },
        { source: "person:jane-smith", target: "company:acme", edge_type: "works_at" },
        { source: "person:bob-jones", target: "company:acme", edge_type: "works_at" },
        { source: "person:alice-chen", target: "company:acme", edge_type: "works_at" },
        { source: "person:dave-wilson", target: "company:globex", edge_type: "works_at" },
        { source: "person:mike", target: "company:initech", edge_type: "works_at" },
      ],
    } : null;
    // ── END DUMMY DATA ──

    const s = get(settings);
    const recordingsDir = s.recordingsFolder;

    let data;
    if (dummyData) {
      data = dummyData;
    } else {
      if (!recordingsDir) {
        error = "No recordings folder configured";
        loading = false;
        return;
      }
      try {
        data = await getGraphData(recordingsDir);
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
        loading = false;
        return;
      }
    }

    try {
      if (data.nodes.length === 0) {
        loading = false;
        return;
      }

      nodes = data.nodes.map((n: GraphNode) => ({
        id: n.id,
        label: n.label,
        node_type: n.node_type,
        x: width / 2 + (Math.random() - 0.5) * 200,
        y: height / 2 + (Math.random() - 0.5) * 200,
      }));

      assignCompanyColors(nodes);

      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      links = data.edges
        .filter((e: GraphEdge) => nodeMap.has(e.source) && nodeMap.has(e.target))
        .map((e: GraphEdge) => ({
          source: nodeMap.get(e.source)!,
          target: nodeMap.get(e.target)!,
          edge_type: e.edge_type,
        }));

      simulation = forceSimulation<SimNode>(nodes)
        .force(
          "link",
          forceLink<SimNode, SimLink>(links)
            .id((d) => d.id)
            .distance(60)
        )
        .force("charge", forceManyBody().strength(-120))
        .force("center", forceCenter(width / 2, height / 2))
        .force("collide", forceCollide<SimNode>().radius((d) => getRadius(d.node_type) + 4))
        .on("tick", () => {
          // Trigger Svelte reactivity by reassigning
          nodes = [...nodes];
          links = [...links];
        });

      loading = false;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      loading = false;
    }
  });

  onDestroy(() => {
    window.removeEventListener("resize", updateSize);
    if (simulation) {
      simulation.stop();
    }
  });
</script>

<div class="graph-container">
  {#if loading}
    <div class="graph-message">Loading graph...</div>
  {:else if error}
    <div class="graph-message graph-error">{error}</div>
  {:else if nodes.length === 0}
    <div class="graph-message">No meeting data to display</div>
  {:else}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <svg
      bind:this={svgEl}
      role="img"
      aria-label="Meeting relationship graph"
      class="graph-svg"
      onpointerdown={handleBgPointerDown}
      onpointermove={handleBgPointerMove}
      onpointerup={handleBgPointerUp}
      onwheel={handleWheel}
    >
      <!-- SVG filter for glow effect -->
      <defs>
        <filter id="node-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <!-- Pan/zoom transform group -->
      <g transform="translate({panX}, {panY}) scale({scale})">
        <!-- Edges -->
        {#each links as link}
          <line
            class="graph-edge {linkOpacityClass(link)}"
            x1={(link.source as SimNode).x ?? 0}
            y1={(link.source as SimNode).y ?? 0}
            x2={(link.target as SimNode).x ?? 0}
            y2={(link.target as SimNode).y ?? 0}
            stroke={isLinkActive(link) ? "#787470" : "#464440"}
            stroke-width={isLinkActive(link) ? 1.5 : 1}
          />
        {/each}

        <!-- Nodes -->
        {#each nodes as node}
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <g
            role="button"
            tabindex="-1"
            class="graph-node {nodeOpacityClass(node.id)}"
            style="cursor: {dragNode === node ? 'grabbing' : 'grab'};"
            filter={hoveredNode === node.id ? "url(#node-glow)" : "none"}
            onpointerdown={(e) => handleNodePointerDown(e, node)}
            onpointermove={handleNodePointerMove}
            onpointerup={handleNodePointerUp}
            onmouseenter={() => handleMouseEnter(node)}
            onmouseleave={handleMouseLeave}
            onclick={() => handleClick(node)}
          >
            <circle
              cx={node.x ?? 0}
              cy={node.y ?? 0}
              r={getRadius(node.node_type)}
              fill={getColor(node)}
            />
            <text
              x={node.x ?? 0}
              y={(node.y ?? 0) + getRadius(node.node_type) + 12}
              text-anchor="middle"
              fill="#78756E"
              font-family="'DM Sans', sans-serif"
              font-size="10"
            >
              {node.label.length > 20 ? node.label.slice(0, 18) + "..." : node.label}
            </text>
          </g>
        {/each}
      </g>
    </svg>

    <!-- Legend -->
    <div class="graph-legend">
      <div class="graph-legend-item">
        <span class="graph-legend-dot" style="background: #A8A078;"></span>
        Meetings
      </div>
      <div class="graph-legend-item">
        <span class="graph-legend-dot" style="background: #78756E;"></span>
        People
      </div>
      <div class="graph-legend-item">
        <span class="graph-legend-dot" style="background: #B4A882;"></span>
        Companies
      </div>
    </div>
  {/if}
</div>

<style>
  .graph-container {
    width: 100%;
    height: calc(100vh - 44px);
    background: #1D1D1B;
    overflow: hidden;
    position: relative;
  }

  .graph-message {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    font-family: 'DM Sans', sans-serif;
    font-size: 13.5px;
    color: #585650;
  }

  .graph-error {
    color: #D06850;
  }

  .graph-svg {
    width: 100%;
    height: 100%;
    touch-action: none;
  }

  /* ── Opacity transitions (Obsidian-style smooth fade) ── */
  .graph-node {
    transition: opacity 200ms ease;
  }

  .graph-node.graph-full {
    opacity: 1;
  }

  .graph-node.graph-dimmed {
    opacity: 0.15;
  }

  .graph-edge {
    transition: opacity 200ms ease, stroke 200ms ease, stroke-width 200ms ease;
  }

  .graph-link-default {
    opacity: 0.6;
  }

  .graph-link-active {
    opacity: 0.8;
  }

  .graph-link-dimmed {
    opacity: 0.05;
  }

  /* ── Legend ── */
  .graph-legend {
    position: absolute;
    bottom: 16px;
    right: 16px;
    display: flex;
    gap: 16px;
    font-family: 'DM Sans', sans-serif;
    font-size: 11px;
    color: #585650;
  }

  .graph-legend-item {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .graph-legend-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }
</style>

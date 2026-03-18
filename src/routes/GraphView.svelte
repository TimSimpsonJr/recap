<script lang="ts">
  import { onMount, onDestroy, untrack } from "svelte";
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
  import GraphControls from "../lib/components/GraphControls.svelte";
  import GraphSidebar from "../lib/components/GraphSidebar.svelte";

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
  let allNodes: SimNode[] = $state([]);
  let allLinks: SimLink[] = $state([]);
  let nodes: SimNode[] = $state([]);
  let links: SimLink[] = $state([]);
  let hoveredNode: string | null = $state(null);
  let connectedIds: Set<string> = $state(new Set());
  let simulation: ReturnType<typeof forceSimulation<SimNode>> | null = null;
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Sidebar state
  let sidebarNode: SimNode | null = $state(null);

  // Drag state
  let dragNode: SimNode | null = $state(null);
  let dragStartX = 0;
  let dragStartY = 0;
  let wasDragged = false;
  const DRAG_THRESHOLD = 3;

  // Pan/zoom state
  let panX = $state(0);
  let panY = $state(0);
  let scale = $state(1);
  let isPanning = $state(false);
  let panStart = { x: 0, y: 0, panX: 0, panY: 0 };

  // Company color map — assigned dynamically
  let companyColorMap: Map<string, string> = new Map();

  // ── Controls state ──
  let filterQuery = $state("");
  let showLabels = $state(true);
  let showArrows = $state(false);
  let showOrphans = $state(true);
  let centerForce = $state(50);
  let repelForce = $state(120);
  let linkDistance = $state(60);
  let linkStrength = $state(50);

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

  // Build groups list for controls panel
  let controlGroups = $derived.by(() => {
    const groups = [
      { label: "Meeting", color: "#A8A078" },
      { label: "Person", color: "#78756E" },
    ];
    for (const [id, color] of companyColorMap.entries()) {
      const node = allNodes.find((n) => n.id === id);
      groups.push({ label: node?.label ?? id, color });
    }
    return groups;
  });

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
    if (dragNode) return;
    hoveredNode = node.id;
    connectedIds = buildConnectedSet(node.id);
  }

  function handleMouseLeave() {
    if (dragNode) return;
    hoveredNode = null;
    connectedIds = new Set();
  }

  // Derive connected meetings for sidebar
  let sidebarConnectedMeetings = $derived.by(() => {
    if (!sidebarNode) return [];
    const nodeId = sidebarNode.id;
    const meetingIds = new Set<string>();

    for (const l of allLinks) {
      const src = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as string);
      const tgt = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as string);
      if (src === nodeId) {
        if (tgt.startsWith("meeting:")) meetingIds.add(tgt);
      }
      if (tgt === nodeId) {
        if (src.startsWith("meeting:")) meetingIds.add(src);
      }
    }

    // For company nodes, also find meetings via connected people
    if (sidebarNode.node_type === "company") {
      const peopleIds = new Set<string>();
      for (const l of allLinks) {
        const src = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as string);
        const tgt = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as string);
        if (tgt === nodeId && src.startsWith("person:")) peopleIds.add(src);
        if (src === nodeId && tgt.startsWith("person:")) peopleIds.add(tgt);
      }
      for (const personId of peopleIds) {
        for (const l of allLinks) {
          const src = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as string);
          const tgt = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as string);
          if (src === personId && tgt.startsWith("meeting:")) meetingIds.add(tgt);
          if (tgt === personId && src.startsWith("meeting:")) meetingIds.add(src);
        }
      }
    }

    return Array.from(meetingIds).map((id) => {
      const node = allNodes.find((n) => n.id === id);
      return { id: id.replace("meeting:", ""), label: node?.label ?? id };
    });
  });

  function handleNodeClick(node: SimNode) {
    if (node.node_type === "meeting") {
      const meetingId = node.id.replace("meeting:", "");
      window.location.hash = `meeting/${meetingId}`;
    } else if (node.node_type === "person" || node.node_type === "company") {
      sidebarNode = node;
    }
  }

  // ── Node drag handlers (with click-vs-drag distance threshold) ──
  function handleNodePointerDown(e: PointerEvent, node: SimNode) {
    e.stopPropagation();
    e.preventDefault();
    dragNode = node;
    wasDragged = false;
    dragStartX = e.clientX;
    dragStartY = e.clientY;

    const world = clientToWorld(e.clientX, e.clientY);

    if (simulation) {
      simulation.alphaTarget(0.3).restart();
    }
    node.fx = node.x;
    node.fy = node.y;

    (dragNode as any)._offsetX = world.x - (node.x ?? 0);
    (dragNode as any)._offsetY = world.y - (node.y ?? 0);

    (e.target as Element).setPointerCapture(e.pointerId);
  }

  function handleNodePointerMove(e: PointerEvent) {
    if (!dragNode || !svgEl) return;
    e.preventDefault();
    e.stopPropagation();

    // Check distance threshold
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    if (!wasDragged && Math.sqrt(dx * dx + dy * dy) > DRAG_THRESHOLD) {
      wasDragged = true;
    }

    if (wasDragged) {
      const world = clientToWorld(e.clientX, e.clientY);
      dragNode.fx = world.x - ((dragNode as any)._offsetX ?? 0);
      dragNode.fy = world.y - ((dragNode as any)._offsetY ?? 0);
    }
  }

  function handleNodePointerUp(e: PointerEvent) {
    if (!dragNode) return;
    e.preventDefault();
    e.stopPropagation();

    const clickedNode = dragNode;
    dragNode.fx = null;
    dragNode.fy = null;

    if (simulation) {
      simulation.alphaTarget(0);
    }

    const didDrag = wasDragged;
    dragNode = null;
    wasDragged = false;

    // If it was a click (not drag), handle the click
    if (!didDrag) {
      handleNodeClick(clickedNode);
    }
  }

  // ── Background pan handlers ──
  function handleBgPointerDown(e: PointerEvent) {
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

  // ── Filter and orphan logic ──
  function applyFilterAndOrphans() {
    const query = filterQuery.toLowerCase().trim();
    let filteredNodes = allNodes;

    if (query) {
      filteredNodes = filteredNodes.filter((n) =>
        n.label.toLowerCase().includes(query)
      );
    }

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    let filteredLinks = allLinks.filter((l) => {
      const src = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as string);
      const tgt = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as string);
      return nodeIds.has(src) && nodeIds.has(tgt);
    });

    if (!showOrphans) {
      const connectedNodeIds = new Set<string>();
      for (const l of filteredLinks) {
        const src = typeof l.source === "object" ? (l.source as SimNode).id : (l.source as string);
        const tgt = typeof l.target === "object" ? (l.target as SimNode).id : (l.target as string);
        connectedNodeIds.add(src);
        connectedNodeIds.add(tgt);
      }
      filteredNodes = filteredNodes.filter((n) => connectedNodeIds.has(n.id));
    }

    nodes = filteredNodes;
    links = filteredLinks;

    untrack(() => {
      if (simulation) {
        simulation.nodes(filteredNodes);
        const linkForce = simulation.force("link") as any;
        if (linkForce) linkForce.links(filteredLinks);
        simulation.alpha(0.3).restart();
      }
    });
  }

  // Watch filter/orphan changes
  $effect(() => {
    filterQuery;
    showOrphans;
    if (allNodes.length > 0) {
      applyFilterAndOrphans();
    }
  });

  // Watch force parameter changes
  $effect(() => {
    // Read the reactive values to track them
    const ld = linkDistance;
    const ls = linkStrength;
    const rf = repelForce;
    const cf = centerForce;

    untrack(() => {
      if (!simulation) return;

      const linkForce = simulation.force("link") as any;
      if (linkForce) {
        linkForce.distance(ld);
        linkForce.strength(ls / 100);
      }

      const chargeForce = simulation.force("charge") as any;
      if (chargeForce) {
        chargeForce.strength(-rf);
      }

      const center = simulation.force("center") as any;
      if (center) {
        center.strength(cf / 100);
      }

      simulation.alpha(0.3).restart();
    });
  });

  onMount(async () => {
    updateSize();
    window.addEventListener("resize", updateSize);

    const s = get(settings);
    const recordingsDir = s.recordingsFolder;

    if (!recordingsDir) {
      error = "No recordings folder configured";
      loading = false;
      return;
    }

    let data;
    try {
      data = await getGraphData(recordingsDir);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      loading = false;
      return;
    }

    try {
      if (data.nodes.length === 0) {
        loading = false;
        return;
      }

      allNodes = data.nodes.map((n: GraphNode) => ({
        id: n.id,
        label: n.label,
        node_type: n.node_type,
        x: width / 2 + (Math.random() - 0.5) * 200,
        y: height / 2 + (Math.random() - 0.5) * 200,
      }));

      assignCompanyColors(allNodes);

      const nodeMap = new Map(allNodes.map((n) => [n.id, n]));
      allLinks = data.edges
        .filter((e: GraphEdge) => nodeMap.has(e.source) && nodeMap.has(e.target))
        .map((e: GraphEdge) => ({
          source: nodeMap.get(e.source)!,
          target: nodeMap.get(e.target)!,
          edge_type: e.edge_type,
        }));

      nodes = [...allNodes];
      links = [...allLinks];

      simulation = forceSimulation<SimNode>(nodes)
        .force(
          "link",
          forceLink<SimNode, SimLink>(links)
            .id((d) => d.id)
            .distance(linkDistance)
            .strength(linkStrength / 100)
        )
        .force("charge", forceManyBody().strength(-repelForce))
        .force("center", forceCenter(width / 2, height / 2).strength(centerForce / 100))
        .force("collide", forceCollide<SimNode>().radius((d) => getRadius(d.node_type) + 4))
        .alphaDecay(0.03)
        .velocityDecay(0.4)
        .on("tick", () => {
          // Only trigger Svelte reactivity update, don't create new arrays
          nodes = nodes;
          links = links;
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
      <!-- SVG defs -->
      <defs>
        <filter id="node-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        {#if showArrows}
          <marker
            id="arrowhead"
            viewBox="0 0 10 7"
            refX="10"
            refY="3.5"
            markerWidth="8"
            markerHeight="6"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#464440" />
          </marker>
          <marker
            id="arrowhead-active"
            viewBox="0 0 10 7"
            refX="10"
            refY="3.5"
            markerWidth="8"
            markerHeight="6"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#787470" />
          </marker>
        {/if}
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
            marker-end={showArrows ? (isLinkActive(link) ? "url(#arrowhead-active)" : "url(#arrowhead)") : "none"}
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
          >
            <circle
              cx={node.x ?? 0}
              cy={node.y ?? 0}
              r={getRadius(node.node_type)}
              fill={getColor(node)}
            />
            {#if showLabels}
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
            {/if}
          </g>
        {/each}
      </g>
    </svg>

    <!-- Controls panel -->
    <GraphControls
      {filterQuery}
      onFilterChange={(q) => filterQuery = q}
      groups={controlGroups}
      {showLabels}
      onShowLabelsChange={(v) => showLabels = v}
      {showArrows}
      onShowArrowsChange={(v) => showArrows = v}
      {showOrphans}
      onShowOrphansChange={(v) => showOrphans = v}
      {centerForce}
      onCenterForceChange={(v) => centerForce = v}
      {repelForce}
      onRepelForceChange={(v) => repelForce = v}
      {linkDistance}
      onLinkDistanceChange={(v) => linkDistance = v}
      {linkStrength}
      onLinkStrengthChange={(v) => linkStrength = v}
    />

    <!-- Graph sidebar for person/company nodes -->
    {#if sidebarNode}
      <GraphSidebar
        nodeId={sidebarNode.id}
        nodeLabel={sidebarNode.label}
        nodeType={sidebarNode.node_type}
        connectedMeetings={sidebarConnectedMeetings}
        onClose={() => sidebarNode = null}
      />
    {/if}

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
    height: calc(100vh - 48px);
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
    font-size: 15px;
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
    font-size: 12.5px;
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

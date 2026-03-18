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
  let dragOffset = { x: 0, y: 0 };

  const NODE_COLORS: Record<string, string> = {
    meeting: "#A8A078",
    person: "#78756E",
    company: "#B4A882",
  };

  const NODE_RADIUS: Record<string, number> = {
    meeting: 8,
    person: 6,
    company: 10,
  };

  function getColor(nodeType: string): string {
    return NODE_COLORS[nodeType] ?? "#78756E";
  }

  function getRadius(nodeType: string): number {
    return NODE_RADIUS[nodeType] ?? 6;
  }

  function updateSize() {
    if (svgEl) {
      const rect = svgEl.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
    }
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
    hoveredNode = node.id;
    connectedIds = buildConnectedSet(node.id);
  }

  function handleMouseLeave() {
    hoveredNode = null;
    connectedIds = new Set();
  }

  function handleClick(node: SimNode) {
    if (node.node_type === "meeting") {
      const meetingId = node.id.replace("meeting:", "");
      window.location.hash = `meeting/${meetingId}`;
    } else {
      window.location.hash = "dashboard";
    }
  }

  function handlePointerDown(e: PointerEvent, node: SimNode) {
    dragNode = node;
    const svgRect = svgEl!.getBoundingClientRect();
    dragOffset.x = e.clientX - svgRect.left - (node.x ?? 0);
    dragOffset.y = e.clientY - svgRect.top - (node.y ?? 0);

    if (simulation) {
      simulation.alphaTarget(0.3).restart();
    }
    node.fx = node.x;
    node.fy = node.y;

    (e.target as Element).setPointerCapture(e.pointerId);
    e.preventDefault();
  }

  function handlePointerMove(e: PointerEvent) {
    if (!dragNode || !svgEl) return;
    const svgRect = svgEl.getBoundingClientRect();
    dragNode.fx = e.clientX - svgRect.left - dragOffset.x;
    dragNode.fy = e.clientY - svgRect.top - dragOffset.y;
    e.preventDefault();
  }

  function handlePointerUp(e: PointerEvent) {
    if (!dragNode) return;
    dragNode.fx = null;
    dragNode.fy = null;
    dragNode = null;

    if (simulation) {
      simulation.alphaTarget(0);
    }
    e.preventDefault();
  }

  function nodeOpacity(nodeId: string): number {
    if (!hoveredNode) return 1;
    return connectedIds.has(nodeId) ? 1 : 0.15;
  }

  function linkOpacity(link: SimLink): number {
    if (!hoveredNode) return 0.6;
    const src = typeof link.source === "object" ? (link.source as SimNode).id : link.source;
    const tgt = typeof link.target === "object" ? (link.target as SimNode).id : link.target;
    if (src === hoveredNode || tgt === hoveredNode) return 0.8;
    return 0.05;
  }

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

    try {
      const data = await getGraphData(recordingsDir);
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

<div
  style="
    width: 100%;
    height: calc(100vh - 44px);
    background: #1D1D1B;
    overflow: hidden;
    position: relative;
  "
>
  {#if loading}
    <div
      style="
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        font-family: 'DM Sans', sans-serif;
        font-size: 13.5px;
        color: #585650;
      "
    >
      Loading graph...
    </div>
  {:else if error}
    <div
      style="
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        font-family: 'DM Sans', sans-serif;
        font-size: 13.5px;
        color: #D06850;
      "
    >
      {error}
    </div>
  {:else if nodes.length === 0}
    <div
      style="
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        font-family: 'DM Sans', sans-serif;
        font-size: 13.5px;
        color: #585650;
      "
    >
      No meeting data to display
    </div>
  {:else}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <svg
      bind:this={svgEl}
      role="img"
      aria-label="Meeting relationship graph"
      style="width: 100%; height: 100%;"
      onpointermove={handlePointerMove}
      onpointerup={handlePointerUp}
    >
      <!-- Edges -->
      {#each links as link}
        <line
          x1={(link.source as SimNode).x ?? 0}
          y1={(link.source as SimNode).y ?? 0}
          x2={(link.target as SimNode).x ?? 0}
          y2={(link.target as SimNode).y ?? 0}
          stroke="#464440"
          stroke-width="1"
          opacity={linkOpacity(link)}
        />
      {/each}

      <!-- Nodes -->
      {#each nodes as node}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <g
          role="button"
          tabindex="-1"
          style="cursor: pointer;"
          opacity={nodeOpacity(node.id)}
          onpointerdown={(e) => handlePointerDown(e, node)}
          onmouseenter={() => handleMouseEnter(node)}
          onmouseleave={handleMouseLeave}
          onclick={() => handleClick(node)}
        >
          <circle
            cx={node.x ?? 0}
            cy={node.y ?? 0}
            r={getRadius(node.node_type)}
            fill={getColor(node.node_type)}
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
    </svg>

    <!-- Legend -->
    <div
      style="
        position: absolute;
        bottom: 16px;
        right: 16px;
        display: flex;
        gap: 16px;
        font-family: 'DM Sans', sans-serif;
        font-size: 11px;
        color: #585650;
      "
    >
      <div style="display: flex; align-items: center; gap: 5px;">
        <span
          style="
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #A8A078;
          "
        ></span>
        Meetings
      </div>
      <div style="display: flex; align-items: center; gap: 5px;">
        <span
          style="
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #78756E;
          "
        ></span>
        People
      </div>
      <div style="display: flex; align-items: center; gap: 5px;">
        <span
          style="
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #B4A882;
          "
        ></span>
        Companies
      </div>
    </div>
  {/if}
</div>

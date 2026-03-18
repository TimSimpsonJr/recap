<script lang="ts">
  import type { PipelineStatus } from "../tauri";

  interface Props {
    status: PipelineStatus;
  }

  let { status }: Props = $props();

  const stages = ["merge", "frames", "transcribe", "diarize", "analyze", "export"] as const;

  let label = $derived.by(() => {
    const failed = stages.find((s) => status[s].error);
    if (failed) return "Failed";

    const allDone = stages.every((s) => status[s].completed);
    if (allDone) return "Complete";

    const lastCompleted = [...stages].reverse().find((s) => status[s].completed);
    if (lastCompleted) {
      const idx = stages.indexOf(lastCompleted);
      if (idx < stages.length - 1) return `Processing: ${stages[idx + 1]}`;
      return "Complete";
    }

    return "Pending";
  });

  let variant = $derived.by(() => {
    if (label === "Failed") return "failed" as const;
    if (label === "Complete") return "done" as const;
    return "active" as const;
  });
</script>

<span
  class="inline-flex items-center"
  style="
    padding: 2px 8px;
    border-radius: 4px;
    font-family: 'DM Sans', sans-serif;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
    background: {variant === 'done' ? 'rgba(160,150,120,0.12)' : variant === 'active' ? 'rgba(180,165,130,0.10)' : 'rgba(200,80,60,0.10)'};
    color: {variant === 'done' ? '#A8A078' : variant === 'active' ? '#B4A882' : '#D06850'};
  "
>
  {label}
</span>

// Selection state management for bulk operations
import { writable, derived } from "svelte/store";

export const selectMode = writable(false);
export const selectedIds = writable<Set<string>>(new Set());

export const selectedCount = derived(selectedIds, ($ids) => $ids.size);

export function toggleSelect(id: string) {
  selectedIds.update((ids) => {
    const next = new Set(ids);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
}

export function selectRange(allIds: string[], fromId: string, toId: string) {
  const fromIdx = allIds.indexOf(fromId);
  const toIdx = allIds.indexOf(toId);
  if (fromIdx === -1 || toIdx === -1) return;
  const [start, end] = fromIdx < toIdx ? [fromIdx, toIdx] : [toIdx, fromIdx];
  selectedIds.update((ids) => {
    const next = new Set(ids);
    for (let i = start; i <= end; i++) next.add(allIds[i]);
    return next;
  });
}

export function selectAll(ids: string[]) {
  selectedIds.update((current) => {
    const next = new Set(current);
    ids.forEach((id) => next.add(id));
    return next;
  });
}

export function clearSelection() {
  selectedIds.set(new Set());
  selectMode.set(false);
}

export function enterSelectMode() {
  selectMode.set(true);
}

export function exitSelectMode() {
  clearSelection();
}

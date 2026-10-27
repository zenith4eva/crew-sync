// Takes this browser uploaded, for picking a before/after pair. Per-viewer convenience only: there is no
// server-side job list, so one crew can't browse another's videos.
export type Take = { id: string; at: number };
const KEY = 'crewsync.takes';

export function loadTakes(): Take[] {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '[]'); } catch { return []; }
}

export function saveTake(id: string) {
  try { localStorage.setItem(KEY, JSON.stringify([{ id, at: Date.now() }, ...loadTakes().filter(t => t.id !== id)].slice(0, 20))); }
  catch { /* storage blocked: compare just lists fewer takes */ }
}

export function forgetTake(id: string) {
  try { localStorage.setItem(KEY, JSON.stringify(loadTakes().filter(t => t.id !== id))); } catch { /* ignore */ }
}

export const takeLabel = (t: Take) =>
  new Date(t.at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

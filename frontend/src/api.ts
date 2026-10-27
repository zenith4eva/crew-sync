export type Status = {
  id: string;
  state: 'queued' | 'running' | 'done' | 'failed';
  step?: string | null;
  error: string | null;
  dancers: number;
  names: Record<string, string>;
  bpm: number | null;
  first_beat: number | null;
  warnings: string[];
  reference?: { state: 'queued' | 'running' | 'scoring' | 'done' | 'failed'; error?: string | null; mirror?: boolean; lag_s?: number } | null;
};

export type Flag = { dancer: string; start_beat: number; end_beat: number; time_s: number; offset_ms: number };
export type Note = { dancer: string; time_s: number; text: string };
export type Dancer = { timing: number | null; formation: number | null; pose?: number | null; score: number | null; offsets_ms: (number | null)[] };

export type Results = {
  crew_score: number | null;
  lowest_dancer: string | null;
  dancers: Record<string, Dancer>;
  flags: Flag[];
  formation_by_beat: Record<string, boolean>[];
  beats: number[];
  n_frames: number;
  fps: number;
  overlay: Record<string, { box: (number[] | null)[]; feet: (number[] | null)[]; outline: (number[] | null)[] }>;
  notes: Note[];
  notes_source: 'muse' | 'template' | null;
  reference: { lag_s: number; mirror: boolean; matches: Record<string, string>; ref_order: string[] } | null;
  pose_flags: { dancer: string; start_beat: number; end_beat: number; time_s: number; limb: string; deg: number }[] | null;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${r.status})`);
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export const api = {
  upload: (form: FormData) => call<Status>('/jobs', { method: 'POST', body: form }),
  status: (id: string) => call<Status>(`/jobs/${id}`),
  results: (id: string) => call<Results>(`/jobs/${id}/results`),
  retry: (id: string) => call<Status>(`/jobs/${id}/retry`, { method: 'POST' }),
  remove: (id: string) => call<{ deleted: string }>(`/jobs/${id}`, { method: 'DELETE' }),
  settings: (id: string, s: { names: Record<string, string>; bpm: number | null; first_beat: number | null; regenerate_notes: boolean }) =>
    call<Results>(`/jobs/${id}/settings`, json(s)),
  fixSwap: (id: string, frame: number, a: string, b: string) => call<Results>(`/jobs/${id}/fix-swap`, json({ frame, a, b })),
  addReference: (id: string, form: FormData) => call<Status>(`/jobs/${id}/reference`, { method: 'POST', body: form }),
  referenceSettings: (id: string, s: { mirror?: boolean; matches?: Record<string, string> }) =>
    call<Results>(`/jobs/${id}/reference/settings`, json(s)),
  removeReference: (id: string) => call<Results>(`/jobs/${id}/reference`, { method: 'DELETE' }),
  videoUrl: (id: string) => `/api/jobs/${id}/video`,
  reelUrl: (id: string) => `/api/jobs/${id}/reel`,
};

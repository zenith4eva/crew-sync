import { useEffect, useState } from 'react';
import { api, Status } from './api';
import ResultsView from './Results';

const jobFromHash = () => new URLSearchParams(location.hash.slice(1)).get('job');

export default function App() {
  const [job, setJob] = useState<string | null>(jobFromHash());
  useEffect(() => {
    const on = () => setJob(jobFromHash());
    addEventListener('hashchange', on);
    return () => removeEventListener('hashchange', on);
  }, []);
  const open = (id: string | null) => { location.hash = id ? `job=${id}` : ''; };

  return (
    <div className="app">
      <header className="top">
        <a className="brand" href="#" onClick={() => open(null)}>Crew Sync</a>
        <span className="tag">every dancer, in sync</span>
      </header>
      {job ? <Job id={job} onLeave={() => open(null)} /> : <Upload onCreated={open} />}
    </div>
  );
}

function Upload({ onCreated }: { onCreated: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dancers, setDancers] = useState(5);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setErr('');
    const form = new FormData();
    form.append('video', file);
    form.append('dancers', String(dancers));
    form.append('consent', String(consent));
    try { onCreated((await api.upload(form)).id); }
    catch (x) { setErr((x as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <form className="card upload" onSubmit={submit}>
      <h1>Score a rehearsal</h1>
      <p className="muted">Film the whole crew from the front on a tripod, 30 to 90 seconds. MP4 or MOV.</p>
      <label className="field">
        <span>Rehearsal video</span>
        <input type="file" accept="video/mp4,video/quicktime,.mp4,.mov" required onChange={e => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span>Dancers in the video</span>
        <input type="number" min={1} max={16} value={dancers} onChange={e => setDancers(Number(e.target.value))} required />
      </label>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} required />
        <span>Every dancer in this video agreed to have it analysed. Uploads are deleted after 7 days.</span>
      </label>
      {err && <p className="error" role="alert">{err}</p>}
      <button className="primary" disabled={busy || !file || !consent}>{busy ? 'Uploading…' : 'Analyse'}</button>
    </form>
  );
}

function Job({ id, onLeave }: { id: string; onLeave: () => void }) {
  const [st, setSt] = useState<Status | null>(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    let stop = false;
    let timer: number;
    const poll = async () => {
      try {
        const s = await api.status(id);
        if (stop) return;
        setSt(s); setErr('');
        if (s.state === 'queued' || s.state === 'running') timer = window.setTimeout(poll, 1500);
      } catch (x) { if (!stop) setErr((x as Error).message); }
    };
    poll();
    return () => { stop = true; clearTimeout(timer); };
  }, [id, st?.state]);

  async function remove() {
    if (!confirm('Delete this video and its results now? This cannot be undone.')) return;
    await api.remove(id);
    onLeave();
  }

  if (err) return <div className="card"><p className="error">{err}</p><button onClick={onLeave}>Back</button></div>;
  if (!st) return <div className="card muted">Loading…</div>;
  if (st.state === 'failed') return (
    <div className="card">
      <h2>That didn't work</h2>
      <p className="error" role="alert">{st.error}</p>
      <div className="row">
        <button className="primary" onClick={async () => setSt(await api.retry(id))}>Retry</button>
        <button onClick={remove}>Delete</button>
      </div>
    </div>
  );
  if (st.state !== 'done') return (
    <div className="card">
      <h2>Analysing your rehearsal</h2>
      <div className="progress" aria-hidden><div /></div>
      <p className="muted">{st.step ?? 'Waiting to start'}…</p>
    </div>
  );
  return <ResultsView id={id} status={st} onDelete={remove} />;
}

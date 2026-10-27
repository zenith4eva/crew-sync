import { Fragment, useEffect, useState } from 'react';
import { api, Status } from './api';
import Compare from './Compare';
import Guide, { TIPS } from './Guide';
import ResultsView from './Results';
import { forgetTake, loadTakes, saveTake, takeLabel } from './takes';

const route = () => new URLSearchParams(location.hash.slice(1));

// The mark: a crew of four in a line, one dancer a step off the beat.
function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden>
      <circle cx="3" cy="11" r="2.5" fill="#fff" />
      <circle cx="8.5" cy="11" r="2.5" fill="#fff" />
      <circle cx="14" cy="6" r="2.5" fill="#c6f24e" />
      <circle cx="19.5" cy="11" r="2.5" fill="#fff" />
    </svg>
  );
}

export default function App() {
  const [params, setParams] = useState(route());
  useEffect(() => {
    const on = () => { setParams(route()); scrollTo(0, 0); };
    addEventListener('hashchange', on);
    return () => removeEventListener('hashchange', on);
  }, []);
  const open = (id: string | null) => { location.hash = id ? `job=${id}` : ''; };
  const job = params.get('job');
  const pair = params.get('compare')?.split(',');
  const where = params.has('guide') ? 'How to film' : pair?.length === 2 ? 'Compare takes' : job ? 'Rehearsal' : 'New rehearsal';

  return (
    <>
      <header className="topbar">
        <a className="brand" href="#"><Mark />Crew Sync</a>
        <span className="crumb"><span aria-hidden>/</span><b>{where}</b></span>
        <nav className="end">
          <a href="#" aria-current={where === 'New rehearsal' ? 'page' : undefined}>New rehearsal</a>
          <a href="#guide" aria-current={where === 'How to film' ? 'page' : undefined}>How to film</a>
        </nav>
      </header>
      <main className="canvas">
        {params.has('guide') ? <Guide />
          : pair?.length === 2 ? <Compare before={pair[0]} after={pair[1]} />
          : job ? <Job id={job} onLeave={() => open(null)} />
          : <Upload onCreated={id => { saveTake(id); open(id); }} />}
      </main>
    </>
  );
}

function Upload({ onCreated }: { onCreated: (id: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dancers, setDancers] = useState(5);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const takes = loadTakes();

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
    <div className="grid start">
      <form className="card upload span-3" onSubmit={submit}>
        <h1>Score a rehearsal</h1>
        <p className="muted">One video of the whole crew, filmed from the front on a tripod, 30 to 90 seconds. MP4 or MOV. <a href="#guide">How to film</a></p>
        <label className="field">
          <span>Rehearsal video</span>
          <input type="file" accept="video/mp4,video/quicktime,.mp4,.mov" required onChange={e => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <div className="field">
          <span id="dancers-label">Dancers in the video</span>
          <div className="stepper">
            <button type="button" aria-label="One fewer dancer" disabled={dancers <= 1} onClick={() => setDancers(dancers - 1)}>−</button>
            <input type="number" aria-labelledby="dancers-label" min={1} max={16} value={dancers} onChange={e => setDancers(Number(e.target.value))} required />
            <button type="button" aria-label="One more dancer" disabled={dancers >= 16} onClick={() => setDancers(dancers + 1)}>+</button>
          </div>
        </div>
        {dancers > 9 && <p className="notice">Above 9 dancers, tracking can mix people up when they cross. You can fix swaps on the results page.</p>}
        <label className="check">
          <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} required />
          <span>Every dancer in this video agreed to have it analyzed. Uploads are deleted after 7 days.</span>
        </label>
        {err && <p className="error" role="alert">{err}</p>}
        <button className="primary" disabled={busy || !file || !consent}>{busy ? 'Uploading…' : 'Analyze rehearsal'}</button>
      </form>
      <div className="span-3 stack">
      <Preview />
      {takes.length > 0 && (
        <section className="card">
          <div className="card-head"><h2>Your takes</h2><span className="end faint small">{takes.length} on this device</span></div>
          <ul className="flags" style={{ marginTop: 0 }}>
            {takes.slice(0, 5).map(t => (
              <li key={t.id} className="go" onClick={() => open(t.id)}>
                <span className="when">Take</span><a className="what" href={`#job=${t.id}`}>{takeLabel(t)}</a><span />
              </li>
            ))}
          </ul>
        </section>
      )}
      </div>
      <section className="card span-6">
        <div className="card-head"><h2>Film it so it scores well</h2><a className="end small" href="#guide">All {TIPS.length} tips</a></div>
        <ul className="tips">
          {TIPS.slice(0, 3).map(([tip, why]) => <li key={tip}><b>{tip}</b><span className="muted">{why}</span></li>)}
        </ul>
      </section>
    </div>
  );
}

// What comes back, drawn in the results screen's own marks: one lane per dancer, a tick per beat.
const EXAMPLE = [
  { name: 'Dancer 1', color: '#ff5d5d', offs: [10, -20, 5, 30, -10, 0, 15, -5, 20, -15, 10, 0, -25, 5, 10, -10, 0, 20, -5, 10] },
  { name: 'Dancer 2', color: '#3ddc84', offs: [0, 15, -10, 5, 20, -5, -160, -210, -180, 10, 0, -15, 5, 10, -20, 0, 15, -10, 5, 0] },
  { name: 'Dancer 3', color: '#4c8dff', offs: [-5, 10, 0, -15, 5, 20, -10, 0, 15, -5, 10, 25, 0, -10, 140, 190, 10, -5, 0, 15] },
  { name: 'Dancer 4', color: '#ffc53d', offs: [5, 0, -10, 15, 0, -5, 10, 20, -15, 0, 5, -10, 15, 0, -5, 10, 0, -20, 10, 5] },
];
// Flagged runs: two or more beats in a row over 120 ms off (beat indices).
const runs = (offs: number[]) => offs.reduce<[number, number][]>((acc, o, b) => {
  if (Math.abs(o) <= 120) return acc;
  const last = acc[acc.length - 1];
  if (last && last[1] === b - 1) last[1] = b; else acc.push([b, b]);
  return acc;
}, []).filter(([s, e]) => e > s);

function Preview() {
  return (
    <section className="card">
      <div className="card-head"><h2>What you get back</h2><span className="end faint small">Example</span></div>
      <div className="lanes">
        {EXAMPLE.map(d => (
          <Fragment key={d.name}>
            <div className="lane-name"><span className="dot" style={{ background: d.color }} />{d.name}</div>
            <div className="lane" style={{ cursor: 'default' }}>
              <svg viewBox="0 0 1000 30" preserveAspectRatio="none" aria-hidden>
                <line x1="0" x2="1000" y1="15" y2="15" stroke="#262626" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                {d.offs.map((o, b) => {
                  const h = Math.max(2, (Math.min(Math.abs(o), 300) / 300) * 13);
                  return <rect key={b} x={25 + b * 50 - 2} width="4" y={o > 0 ? 15 - h : 15} height={h} rx="1" fill={Math.abs(o) <= 100 ? '#c6f24e' : '#fff'} />;
                })}
              </svg>
              {runs(d.offs).map(([s, e]) => <span key={s} className="run" style={{ left: `${s * 5}%`, width: `${(e - s + 1) * 5}%` }} />)}
            </div>
          </Fragment>
        ))}
      </div>
      <ul className="gets">
        <li><b>A Crew Sync Score</b> out of 100, and who has the most to gain.</li>
        <li><b>Every dancer's timing</b> against the rest of the crew, beat by beat, with the moments to fix.</li>
        <li><b>The formation from above</b>, and where spacing breaks.</li>
        <li><b>Coaching notes</b> written by Muse Spark, and a 20-second Reel to share.</li>
      </ul>
    </section>
  );
}

const open = (id: string) => { location.hash = `job=${id}`; };
const STEPS = ['preparing video', 'tracking dancers with SAM 3.1', 'scoring'];

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
    forgetTake(id);
    onLeave();
  }

  if (err) return <div className="card narrow"><p className="error">{err}</p><button onClick={onLeave} style={{ marginTop: 12 }}>Back</button></div>;
  if (!st) return <div className="card narrow muted">Loading…</div>;
  if (st.state === 'failed') return (
    <div className="card narrow stack">
      <h1>That didn't work</h1>
      <p className="error" role="alert">{st.error}</p>
      <div className="row">
        <button className="primary" onClick={async () => setSt(await api.retry(id))}>Retry</button>
        <button onClick={remove}>Delete</button>
      </div>
    </div>
  );
  if (st.state !== 'done') {
    const now = st.step?.includes('pose') ? 1 : Math.max(0, STEPS.indexOf(st.step ?? ''));
    return (
      <div className="card narrow">
        <h1>Analyzing your rehearsal</h1>
        <p className="muted" style={{ marginTop: 4 }}>{st.dancers} dancers · usually under a minute</p>
        <div className="progress" aria-hidden><div /></div>
        <ol className="steps" aria-live="polite">
          {['Preparing the video', 'Tracking every dancer with SAM 3.1', 'Scoring timing and formation'].map((s, i) => (
            <li key={s} className={st.state === 'queued' ? '' : i < now ? 'done' : i === now ? 'now' : ''}>{s}</li>
          ))}
        </ol>
      </div>
    );
  }
  return <ResultsView id={id} status={st} onDelete={remove} />;
}

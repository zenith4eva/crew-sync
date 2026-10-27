import { useEffect, useMemo, useRef, useState } from 'react';
import { api, Results, Status } from './api';
import LabelMode from './LabelMode';
import ReferencePanel from './Reference';
import { loadTakes, takeLabel } from './takes';

const COLORS = ['#ff5d5d', '#3ddc84', '#4c8dff', '#ffc53d', '#d36bff', '#2fd3d3', '#ff8a3d', '#a3e635',
  '#f472b6', '#94a3b8', '#facc15', '#60a5fa', '#34d399', '#fb7185', '#c084fc', '#fdba74'];

const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const pct = (v: number | null) => (v === null ? '–' : Math.round(v).toString());

export default function ResultsView({ id, status, onDelete }: { id: string; status: Status; onDelete: () => void }) {
  const [res, setRes] = useState<Results | null>(null);
  const [names, setNames] = useState<Record<string, string>>(status.names);
  const [bpm, setBpm] = useState(status.bpm?.toString() ?? '');
  const [firstBeat, setFirstBeat] = useState(status.first_beat?.toString() ?? '');
  const [warnings, setWarnings] = useState(status.warnings);
  const [frame, setFrame] = useState(0);
  const [vsize, setVsize] = useState<[number, number]>([0, 0]);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => { api.results(id).then(setRes, e => setErr(e.message)); }, [id]);

  const ids = useMemo(() => (res ? Object.keys(res.dancers).sort((a, b) => Number(a) - Number(b)) : []), [res]);
  const color = (d: string) => COLORS[ids.indexOf(d) % COLORS.length];
  const label = (d: string) => names[d] || `Dancer ${ids.indexOf(d) + 1}`;

  // Track the video frame while playing or seeking.
  useEffect(() => {
    const v = video.current;
    if (!v || !res) return;
    let raf = 0;
    const tick = () => {
      setFrame(Math.min(res.n_frames - 1, Math.floor(v.currentTime * res.fps + 1e-3)));
      if (!v.paused) raf = requestAnimationFrame(tick);
    };
    const events = ['play', 'seeked', 'timeupdate', 'loadeddata'];
    events.forEach(e => v.addEventListener(e, tick));
    return () => { cancelAnimationFrame(raf); events.forEach(e => v.removeEventListener(e, tick)); };
  }, [res]);

  const seek = (t: number) => { if (video.current) { video.current.currentTime = t; video.current.pause(); } };

  async function run(what: string, fn: () => Promise<Results>) {
    setBusy(what); setErr('');
    try { setRes(await fn()); setWarnings((await api.status(id)).warnings); }
    catch (x) { setErr((x as Error).message); }
    finally { setBusy(''); }
  }

  async function exportReel() {
    setBusy('reel'); setErr('');
    try {
      const r = await fetch(api.reelUrl(id));
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? 'Reel export failed');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(await r.blob());
      a.download = 'crew-sync-reel.mp4';
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (x) { setErr((x as Error).message); }
    finally { setBusy(''); }
  }

  if (!res) return <div className="card">{err ? <p className="error">{err}</p> : <span className="muted">Loading results…</span>}</div>;

  const duration = res.n_frames / res.fps;
  const t = frame / res.fps;
  const lowest = res.lowest_dancer;

  return (
    <div className="results">
      <section className="card score">
        <div>
          <div className="eyebrow">Crew Sync Score</div>
          <div className="big">{pct(res.crew_score)}</div>
        </div>
        {lowest && <p>Most to gain: <b style={{ color: color(lowest) }}>{label(lowest)}</b> ({pct(res.dancers[lowest].score)})</p>}
        <CompareWith id={id} />
        <div className="row actions">
          <button className="primary" disabled={!!busy} onClick={exportReel}>{busy === 'reel' ? 'Rendering reel…' : 'Export Sync Score Reel'}</button>
          <button className="ghost" onClick={onDelete}>Delete video</button>
        </div>
      </section>

      {warnings.map(w => <p key={w} className="warn">{w}</p>)}
      {err && <p className="error" role="alert">{err}</p>}

      <div className="grid">
        <section className="card player">
          <div className="stage">
            <video ref={video} src={api.videoUrl(id)} controls playsInline
              onLoadedMetadata={e => setVsize([e.currentTarget.videoWidth, e.currentTarget.videoHeight])} />
            <Overlay res={res} frame={frame} ids={ids} color={color} label={label} size={vsize} />
          </div>
          <Timeline res={res} duration={duration} t={t} seek={seek} label={label} color={color} />
          <FixSwap ids={ids} label={label} t={t} busy={busy === 'swap'}
            onSwap={(a, b) => run('swap', () => api.fixSwap(id, frame, a, b))} />
          <LabelMode id={id} ids={ids} label={label} color={color} video={video} />
        </section>

        <section className="card">
          <h3>Formation</h3>
          <FormationMap res={res} frame={frame} ids={ids} color={color} />
          <p className="muted small">Top-down from feet positions. Arrows show drift since the last beat; red rings are out of formation.</p>
        </section>

        <section className="card">
          <h3>Dancers</h3>
          <table className="dancers">
            <thead><tr><th>Name</th><th>Score</th><th>Timing</th><th>Formation</th>{res.pose_flags && <th>Pose</th>}</tr></thead>
            <tbody>
              {ids.map(d => (
                <tr key={d}>
                  <td>
                    <span className="dot" style={{ background: color(d) }} />
                    <input aria-label={`Name for ${label(d)}`} value={names[d] ?? ''} placeholder={`Dancer ${ids.indexOf(d) + 1}`}
                      onChange={e => setNames({ ...names, [d]: e.target.value })} />
                  </td>
                  <td><b>{pct(res.dancers[d].score)}</b></td>
                  <td>{pct(res.dancers[d].timing)}</td>
                  <td>{pct(res.dancers[d].formation)}</td>
                  {res.pose_flags && <td>{pct(res.dancers[d].pose ?? null)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row bpm">
            <label>BPM <input type="number" min={40} max={240} step="0.1" value={bpm} placeholder="auto" onChange={e => setBpm(e.target.value)} /></label>
            <label>First beat (s) <input type="number" min={0} step="0.01" value={firstBeat} placeholder="0" onChange={e => setFirstBeat(e.target.value)} /></label>
            <button disabled={!!busy} onClick={() => run('save', () => api.settings(id, {
              names, bpm: bpm ? Number(bpm) : null, first_beat: firstBeat ? Number(firstBeat) : null, regenerate_notes: true,
            }))}>{busy === 'save' ? 'Rescoring…' : 'Save and rescore'}</button>
          </div>
        </section>

        {res.pose_flags && (
          <section className="card">
            <h3>Body pose</h3>
            <p className="muted small">SAM 3D Body on each beat: limbs more than 25° off the crew's shape.</p>
            <ul className="flags">
              {[...res.pose_flags].sort((a, b) => b.deg - a.deg).slice(0, 6).sort((a, b) => a.time_s - b.time_s).map((f, i) => (
                <li key={i}><button className="link" onClick={() => seek(f.time_s)}>{mmss(f.time_s)}</button>{' '}
                  <b style={{ color: color(f.dancer) }}>{label(f.dancer)}</b>: {f.limb} up to {f.deg}° off{f.end_beat > f.start_beat ? ` for ${f.end_beat - f.start_beat + 1} beats` : ''}</li>
              ))}
              {!res.pose_flags.length && <li className="muted">Every limb matches the crew. Clean.</li>}
            </ul>
          </section>
        )}

        <section className="card">
          <h3>Coaching notes</h3>
          {res.notes_source === 'template' && <p className="muted small">Auto-generated, Muse unavailable.</p>}
          <ol className="notes">
            {res.notes.map((n, i) => {
              const who = ids.find(d => label(d) === n.dancer);
              return (
                <li key={i}>
                  <b style={{ color: who ? color(who) : undefined }}>{n.dancer === 'crew' ? 'Whole crew' : n.dancer}</b>
                  {n.time_s > 0 && <> · <button className="link" onClick={() => seek(n.time_s)}>{mmss(n.time_s)}</button></>}
                  <br />{n.text}
                </li>
              );
            })}
          </ol>
        </section>

        <ReferencePanel id={id} res={res} ids={ids} label={label} color={color}
          onResults={r => { setRes(r); api.status(id).then(s => setWarnings(s.warnings), () => {}); }} />
      </div>
    </div>
  );
}

function CompareWith({ id }: { id: string }) {
  const others = loadTakes().filter(t => t.id !== id);
  if (!others.length) return null;
  return (
    <label className="compare-pick">
      <span className="muted small">Compare with an earlier take</span>
      <select value="" onChange={e => { if (e.target.value) location.hash = `compare=${e.target.value},${id}`; }}>
        <option value="">Choose a take…</option>
        {others.map(t => <option key={t.id} value={t.id}>{takeLabel(t)}</option>)}
      </select>
    </label>
  );
}

type Draw = { res: Results; frame: number; ids: string[]; color: (d: string) => string };

function Overlay({ res, frame, ids, color, label, size }: Draw & { label: (d: string) => string; size: [number, number] }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const c = ref.current;
    if (!c || !size[0]) return; // boxes are in video pixels; wait for the video's real size
    c.width = size[0]; c.height = size[1];
    const g = c.getContext('2d')!;
    g.clearRect(0, 0, c.width, c.height);
    g.lineWidth = Math.max(2, c.height / 240);
    g.font = `600 ${Math.max(12, c.height / 32)}px system-ui`;
    for (const d of ids) {
      const b = res.overlay[d].box[frame];
      if (!b) continue;
      g.strokeStyle = g.fillStyle = color(d);
      const o = res.overlay[d].outline?.[frame];
      if (o) {
        g.beginPath();
        for (let k = 0; k < o.length; k += 2) (k ? g.lineTo : g.moveTo).call(g, o[k], o[k + 1]);
        g.closePath(); g.stroke();
      } else g.strokeRect(b[0], b[1], b[2] - b[0], b[3] - b[1]);
      g.fillText(label(d), b[0], b[1] - 6);
      const f = res.overlay[d].feet[frame];
      if (f) { g.beginPath(); g.arc(f[0], f[1], g.lineWidth * 2, 0, Math.PI * 2); g.fill(); }
    }
  });
  return <canvas ref={ref} className="overlay" />;
}

function FormationMap({ res, frame, ids, color }: Draw) {
  const ref = useRef<HTMLCanvasElement>(null);
  const bounds = useMemo(() => {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const d of ids) for (const p of res.overlay[d].feet) if (p) {
      x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]);
    }
    const pad = Math.max(20, (x1 - x0) * 0.1);
    return { x0: x0 - pad, x1: x1 + pad, y0: y0 - pad, y1: y1 + pad };
  }, [res, ids]);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const W = (c.width = 480), H = (c.height = 300);
    const g = c.getContext('2d')!;
    g.fillStyle = getComputedStyle(c).getPropertyValue('--floor') || '#1b1f27';
    g.fillRect(0, 0, W, H);
    const s = Math.min(W / (bounds.x1 - bounds.x0), H / Math.max(1, bounds.y1 - bounds.y0));
    const px = (p: number[]) => [(p[0] - bounds.x0) * s + (W - (bounds.x1 - bounds.x0) * s) / 2, (p[1] - bounds.y0) * s + (H - (bounds.y1 - bounds.y0) * s) / 2];
    const t = frame / res.fps;
    let b = -1;
    for (let i = 0; i < res.beats.length && res.beats[i] <= t; i++) b = i;
    const prevFrame = b > 0 ? Math.round(res.beats[b - 1] * res.fps) : -1;
    g.font = '600 12px system-ui';
    g.fillStyle = '#8b93a7';
    g.fillText('audience / camera', 8, H - 8);
    for (const d of ids) {
      const p = res.overlay[d].feet[frame];
      if (!p) continue;
      const [x, y] = px(p);
      const q = prevFrame >= 0 ? res.overlay[d].feet[prevFrame] : null;
      g.strokeStyle = g.fillStyle = color(d);
      if (q) {
        const [qx, qy] = px(q);
        if (Math.hypot(x - qx, y - qy) > 3) {
          g.lineWidth = 2;
          g.beginPath(); g.moveTo(qx, qy); g.lineTo(x, y); g.stroke();
          const a = Math.atan2(y - qy, x - qx);
          g.beginPath(); g.moveTo(x, y);
          g.lineTo(x - 8 * Math.cos(a - 0.4), y - 8 * Math.sin(a - 0.4));
          g.lineTo(x - 8 * Math.cos(a + 0.4), y - 8 * Math.sin(a + 0.4));
          g.fill();
        }
      }
      g.beginPath(); g.arc(x, y, 7, 0, Math.PI * 2); g.fill();
      if (b >= 0 && res.formation_by_beat[b]?.[d] === false) {
        g.strokeStyle = '#ff3b3b'; g.lineWidth = 3;
        g.beginPath(); g.arc(x, y, 12, 0, Math.PI * 2); g.stroke();
      }
    }
  });
  return <canvas ref={ref} className="formation" aria-label="Formation map" />;
}

function Timeline({ res, duration, t, seek, label, color }: {
  res: Results; duration: number; t: number; seek: (t: number) => void; label: (d: string) => string; color: (d: string) => string;
}) {
  // Biggest problems first: how far off, times how many beats in a row; then shown in time order.
  const cost = (f: Results['flags'][number]) => Math.abs(f.offset_ms) * (f.end_beat - f.start_beat + 1);
  const worst = [...res.flags].sort((a, b) => cost(b) - cost(a)).slice(0, 6).sort((a, b) => a.time_s - b.time_s);
  return (
    <div className="timeline-wrap">
      <div className="timeline" onClick={e => {
        const r = e.currentTarget.getBoundingClientRect();
        seek(((e.clientX - r.left) / r.width) * duration);
      }}>
        <div className="playhead" style={{ left: `${(t / duration) * 100}%` }} />
        {res.flags.map((f, i) => (
          <button key={i} className="flag" style={{ left: `${(f.time_s / duration) * 100}%`, background: color(f.dancer) }}
            title={`${label(f.dancer)} ${Math.abs(f.offset_ms)} ms ${f.offset_ms > 0 ? 'late' : 'early'} at ${mmss(f.time_s)}`}
            onClick={e => { e.stopPropagation(); seek(f.time_s); }} />
        ))}
      </div>
      <ul className="flags">
        {worst.map((f, i) => (
          <li key={i}><button className="link" onClick={() => seek(f.time_s)}>{mmss(f.time_s)}</button>{' '}
            <b style={{ color: color(f.dancer) }}>{label(f.dancer)}</b> is {Math.abs(f.offset_ms)} ms {f.offset_ms > 0 ? 'late' : 'early'}</li>
        ))}
        {!res.flags.length && <li className="muted">No flagged moments. Nice.</li>}
        {res.flags.length > worst.length && <li className="muted small">The {worst.length} biggest of {res.flags.length} flagged moments. The rest are on the timeline.</li>}
      </ul>
    </div>
  );
}

function FixSwap({ ids, label, t, busy, onSwap }: { ids: string[]; label: (d: string) => string; t: number; busy: boolean; onSwap: (a: string, b: string) => void }) {
  const [a, setA] = useState(ids[0] ?? '');
  const [b, setB] = useState(ids[1] ?? '');
  return (
    <details className="fix">
      <summary>Colors swapped after a crossing? Fix it</summary>
      <div className="row">
        <select value={a} onChange={e => setA(e.target.value)} aria-label="First dancer">{ids.map(d => <option key={d} value={d}>{label(d)}</option>)}</select>
        <span>and</span>
        <select value={b} onChange={e => setB(e.target.value)} aria-label="Second dancer">{ids.map(d => <option key={d} value={d}>{label(d)}</option>)}</select>
        <button disabled={busy || a === b} onClick={() => onSwap(a, b)}>{busy ? 'Fixing…' : `Swap from ${mmss(t)}`}</button>
      </div>
    </details>
  );
}

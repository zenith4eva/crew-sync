import { useEffect, useMemo, useRef, useState } from 'react';
import { api, Flag, Results, Status } from './api';
import LabelMode from './LabelMode';
import ReferencePanel from './Reference';
import { loadTakes, takeLabel } from './takes';

const COLORS = ['#ff5d5d', '#3ddc84', '#4c8dff', '#ffc53d', '#ff9ecb', '#2fd3d3', '#ff8a3d', '#a3e635',
  '#f472b6', '#94a3b8', '#facc15', '#7cc4ff', '#34d399', '#fb7185', '#e0b07a', '#fdba74'];

// taste-skill-ignore: clock time, not numbering
const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const pct = (v: number | null) => (v === null ? '–' : Math.round(v).toString());
const TOL_MS = 100; // config.TIMING_TOL_S
// Biggest problems first: how far off, times how many beats in a row.
const cost = (f: Flag) => Math.abs(f.offset_ms) * (f.end_beat - f.start_beat + 1);
const biggest = (flags: Flag[]) => [...flags].sort((a, b) => cost(b) - cost(a));

export default function ResultsView({ id, status, onDelete }: { id: string; status: Status; onDelete: () => void }) {
  const [res, setRes] = useState<Results | null>(null);
  const [names, setNames] = useState<Record<string, string>>(status.names);
  const [bpm, setBpm] = useState(status.bpm?.toString() ?? '');
  const [firstBeat, setFirstBeat] = useState(status.first_beat?.toString() ?? '');
  const [warnings, setWarnings] = useState(status.warnings);
  const [saved, setSaved] = useState({ names: status.names, bpm: status.bpm });
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
  const [picked, setPicked] = useState<Flag | null>(null);
  const pick = (f: Flag) => { setPicked(f); seek(f.time_s); };
  const save = () => run('save', () => api.settings(id, {
    names, bpm: bpm ? Number(bpm) : null, first_beat: firstBeat ? Number(firstBeat) : null, regenerate_notes: true,
  }));

  async function run(what: string, fn: () => Promise<Results>) {
    setBusy(what); setErr('');
    try {
      setRes(await fn());
      const s = await api.status(id);
      setWarnings(s.warnings); setSaved({ names: s.names, bpm: s.bpm });
    }
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

  if (!res) return <ResultsSkeleton err={err} />;

  const duration = res.n_frames / res.fps;
  const t = frame / res.fps;
  const lowest = res.lowest_dancer;
  const offs = ids.flatMap(d => res.dancers[d].offsets_ms).filter((o): o is number => o !== null);
  const inSync = offs.length ? Math.round((offs.filter(o => Math.abs(o) <= TOL_MS).length / offs.length) * 100) : null;
  const worst = biggest(res.flags)[0];
  const created = status.created ? new Date(status.created * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : null;
  const namesChanged = ids.some(d => (names[d] ?? '') !== (saved.names[d] ?? ''));

  return (
    <div className="arrive">
      <div className="title-row">
        <div>
          <h1>{created ? `Take of ${created}` : 'Rehearsal take'}</h1>
          <p className="lede">
            {worst
              ? <><b>{label(worst.dancer)}</b> was {Math.abs(worst.offset_ms)} ms {worst.offset_ms > 0 ? 'late' : 'early'} at{' '}
                  <button className="link" onClick={() => pick(worst)}>{mmss(worst.time_s)}</button>, the biggest miss in this take.</>
              : 'Every dancer stayed with the crew on every beat.'}
          </p>
        </div>
        <div className="actions">
          <CompareWith id={id} />
          <button className="ghost" onClick={onDelete}>Delete video</button>
          <button className="primary" disabled={!!busy} onClick={exportReel}>{busy === 'reel' ? 'Rendering reel…' : 'Export Sync Score Reel'}</button>
        </div>
      </div>

      {warnings.map(w => <p key={w} className="notice">{w}</p>)}
      {err && <p className="notice error" role="alert">{err}</p>}

      <section className="kpis" aria-label="Summary">
        <div className="kpi">
          <span className="kpi-label">Crew Sync Score</span>
          <span className="kpi-value lead">{res.crew_score === null ? '–' : <CountUp to={Math.round(res.crew_score)} />}<span className="unit">/100</span></span>
          <span className="kpi-sub">0.6 timing + 0.4 formation, averaged over {ids.length} dancers</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Beats in sync</span>
          <span className="kpi-value">{inSync === null ? '–' : <>{inSync}<span className="unit">%</span></>}</span>
          <span className="kpi-sub">within ±{TOL_MS} ms of the crew, of {offs.length} dancer-beats</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Flagged moments</span>
          <span className="kpi-value">{res.flags.length}</span>
          <span className="kpi-sub">2+ beats in a row over 120 ms off</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">Most to gain</span>
          <span className="kpi-value">{lowest ? <><span className="dot" style={{ background: color(lowest), marginRight: 10, verticalAlign: 4 }} />{label(lowest)}</> : '–'}</span>
          <span className="kpi-sub">{lowest ? `scores ${pct(res.dancers[lowest].score)}, the crew's lowest` : 'no dancer scored'}</span>
        </div>
      </section>

      <div className="grid">
        <section className="card span-4" aria-label="Video">
          <div className="stage">
            <video ref={video} src={api.videoUrl(id)} controls playsInline preload="auto"
              onLoadedMetadata={e => setVsize([e.currentTarget.videoWidth, e.currentTarget.videoHeight])} />
            <Overlay res={res} frame={frame} ids={ids} color={color} label={label} size={vsize} />
          </div>
          <SyncStrip res={res} ids={ids} duration={duration} t={t} seek={seek} pick={pick} picked={picked} label={label} color={color} />
          <FlagList res={res} pick={pick} picked={picked} label={label} color={color} />
        </section>

        <div className="span-2 stack">
          <section className="card">
            <div className="card-head"><h2>Dancers</h2><span className="end faint small">Tap a name to rename</span></div>
            <table className="dancers">
              <thead><tr><th>Name</th><th className="num">Score</th><th className="num">Timing</th><th className="num">Form.</th>{res.pose_flags && <th className="num">Pose</th>}</tr></thead>
              <tbody>
                {ids.map(d => (
                  <tr key={d}>
                    <td>
                      <span className="name-cell">
                        <span className="dot" style={{ background: color(d) }} />
                        <input aria-label={`Name for ${label(d)}`} value={names[d] ?? ''} placeholder={`Dancer ${ids.indexOf(d) + 1}`}
                          onChange={e => setNames({ ...names, [d]: e.target.value })} />
                      </span>
                    </td>
                    <td className="num"><b>{pct(res.dancers[d].score)}</b>
                      <div className="bar" aria-hidden><span style={{ width: `${res.dancers[d].score ?? 0}%` }} /></div></td>
                    <td className="num muted">{pct(res.dancers[d].timing)}</td>
                    <td className="num muted">{pct(res.dancers[d].formation)}</td>
                    {res.pose_flags && <td className="num muted">{pct(res.dancers[d].pose ?? null)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
            {namesChanged && (
              <div className="row" style={{ marginTop: 12 }}>
                <button className="primary" disabled={!!busy} onClick={save}>{busy === 'save' ? 'Rescoring…' : 'Save names'}</button>
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head"><h2>Formation</h2><span className="end faint small">From above, beat by beat</span></div>
            <FormationMap res={res} frame={frame} ids={ids} color={color} />
            <p className="faint small" style={{ marginTop: 10 }}>Feet positions; a tail shows drift since the last beat and a red ring is out of formation.</p>
          </section>

          <section className="card" aria-label="Tools">
            <details className="tool">
              <summary>Beat grid<span className="pill neutral">{saved.bpm ? `${saved.bpm} BPM` : 'Auto'}</span></summary>
              <div className="body">
                <p className="muted">Set the tempo by hand when the music is quiet or missing.</p>
                <div className="fields">
                  <label>BPM <input type="number" min={40} max={240} step="0.1" value={bpm} placeholder="auto" onChange={e => setBpm(e.target.value)} /></label>
                  <label>First beat (s) <input type="number" min={0} step="0.01" value={firstBeat} placeholder="0" onChange={e => setFirstBeat(e.target.value)} /></label>
                  <button disabled={!!busy} onClick={save}>{busy === 'save' ? 'Rescoring…' : 'Save and rescore'}</button>
                </div>
              </div>
            </details>
            <FixSwap ids={ids} label={label} t={t} busy={busy === 'swap'}
              onSwap={(a, b) => run('swap', () => api.fixSwap(id, frame, a, b))} />
            <LabelMode id={id} ids={ids} flags={res.flags} beats={res.beats} label={label} color={color} video={video} />
            <ReferencePanel id={id} res={res} ids={ids} label={label} color={color}
              onResults={r => { setRes(r); api.status(id).then(s => setWarnings(s.warnings), () => {}); }} />
          </section>
        </div>

        {res.pose_flags && (
          <section className="card span-6">
            <div className="card-head"><h2>Body pose</h2><span className="end faint small">Limbs over 25° off the crew's shape</span></div>
            <ul className="flags" style={{ marginTop: 0 }}>
              {[...res.pose_flags].sort((a, b) => b.deg - a.deg).slice(0, 6).sort((a, b) => a.time_s - b.time_s).map((f, i) => (
                <li key={i} className="go" onClick={() => seek(f.time_s)}>
                  <span className="when">{mmss(f.time_s)}</span>
                  <span className="what"><span className="dot" style={{ background: color(f.dancer), marginRight: 8 }} /><b>{label(f.dancer)}</b> {f.limb}</span>
                  <span className="pill neg">{f.deg}° off</span>
                </li>
              ))}
              {!res.pose_flags.length && <li className="faint">Every limb matches the crew.</li>}
            </ul>
          </section>
        )}

        <section className="card span-6">
          <div className="card-head"><h2>Coaching notes</h2>
            <span className="end faint small">{res.notes_source === 'template' ? 'Built from the numbers; Muse was unavailable' : 'Written by Muse Spark from the numbers'}</span></div>
          <ol className="notes">
            {res.notes.map((n, i) => {
              const who = ids.find(d => label(d) === n.dancer);
              return (
                <li key={i}>
                  <span className="who">
                    <b>{who && <span className="dot" style={{ background: color(who) }} />}{n.dancer === 'crew' ? 'Whole crew' : n.dancer}</b>
                    {n.time_s > 0 && <button className="link faint small" style={{ justifySelf: 'start' }} onClick={() => seek(n.time_s)}>at {mmss(n.time_s)}</button>}
                  </span>
                  <p>{n.text}</p>
                </li>
              );
            })}
          </ol>
        </section>


      </div>
    </div>
  );
}

function ResultsSkeleton({ err }: { err: string }) {
  if (err) return <div className="card narrow"><p className="error" role="alert">{err}</p></div>;
  return (
    <div aria-busy>
      <div className="title-row"><div><h1>Loading results…</h1><div className="skel" style={{ width: 340, height: 16, marginTop: 8 }} /></div></div>
      <section className="kpis">
        {['Crew Sync Score', 'Beats in sync', 'Flagged moments', 'Most to gain'].map((l, i) => (
          <div className="kpi" key={l}><span className="kpi-label">{l}</span><div className="skel" style={{ width: 72, height: i ? 32 : 36 }} /></div>
        ))}
      </section>
      <div className="grid">
        <section className="card span-4"><div className="skel" style={{ aspectRatio: '16 / 9' }} /></section>
        <section className="card span-2"><div className="skel" style={{ height: 240 }} /></section>
      </div>
    </div>
  );
}

// The crew score counts up once when the results land.
function CountUp({ to }: { to: number }) {
  const [v, setV] = useState(matchMedia('(prefers-reduced-motion: reduce)').matches ? to : 0);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 900);
      setV(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return <>{v}</>;
}

// Signature element: one lane per dancer across the clip. A tick per beat shows that dancer's offset
// from the crew (up = late, down = early); lime within ±100 ms, white beyond; flagged runs are red bands.
function SyncStrip({ res, ids, duration, t, seek, pick, picked, label, color }: {
  res: Results; ids: string[]; duration: number; t: number; seek: (t: number) => void; pick: (f: Flag) => void; picked: Flag | null;
  label: (d: string) => string; color: (d: string) => string;
}) {
  const H = 30, MAX = 300;
  const x = (s: number) => (s / duration) * 100;
  const beatEnd = (b: number) => res.beats[b + 1] ?? res.beats[b] + (res.beats[1] - res.beats[0] || 0.5);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(k => mmss(k * duration));
  return (
    <div className="strip">
      <div className="strip-head">
        <h2>Timing, dancer by dancer</h2>
        <div className="legend">
          <span><i style={{ background: 'var(--accent)' }} />In sync</span>
          <span><i style={{ background: '#fff' }} />Off the crew</span>
          <span><i className="flagged" />Flagged</span>
        </div>
      </div>
      <div className="lanes">
        {ids.map(d => (
          <Lane key={d}>
            <div className="lane-name"><span className="dot" style={{ background: color(d) }} />{label(d)}</div>
            <div className="lane" onClick={e => { const r = e.currentTarget.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * duration); }}>
              <svg viewBox={`0 0 1000 ${H}`} preserveAspectRatio="none" aria-hidden>
                <line x1="0" x2="1000" y1={H / 2} y2={H / 2} stroke="#262626" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                {res.dancers[d].offsets_ms.map((o, b) => {
                  if (o === null) return null;
                  const h = Math.max(2, (Math.min(Math.abs(o), MAX) / MAX) * (H / 2 - 2));
                  const cx = x(res.beats[b]) * 10;
                  return <rect key={b} x={cx - 2} width="4" y={o > 0 ? H / 2 - h : H / 2} height={h} rx="1"
                    fill={Math.abs(o) <= TOL_MS ? 'var(--accent)' : '#ffffff'} />;
                })}
              </svg>
              {res.flags.filter(f => f.dancer === d).map((f, i) => (
                <button key={i} className={`run${picked === f ? ' on' : ''}`}
                  style={{ left: `${x(res.beats[f.start_beat])}%`, width: `${x(beatEnd(f.end_beat)) - x(res.beats[f.start_beat])}%` }}
                  aria-label={`${label(d)} ${Math.abs(f.offset_ms)} ms ${f.offset_ms > 0 ? 'late' : 'early'} at ${mmss(f.time_s)}`}
                  onClick={e => { e.stopPropagation(); pick(f); }} />
              ))}
            </div>
          </Lane>
        ))}
        <div className="playhead-track"><div className="playhead" style={{ left: `${x(t)}%` }} /></div>
      </div>
      <div className="axis"><span /><div>{ticks.map((k, i) => <span key={i}>{k}</span>)}</div></div>
    </div>
  );
}

const Lane = ({ children }: { children: React.ReactNode }) => <>{children}</>;

function FlagList({ res, pick, picked, label, color }: {
  res: Results; pick: (f: Flag) => void; picked: Flag | null; label: (d: string) => string; color: (d: string) => string;
}) {
  const shown = biggest(res.flags).slice(0, 5).sort((a, b) => a.time_s - b.time_s);
  return (
    <ul className="flags">
      {shown.map((f, i) => (
        <li key={i} className={`go${picked === f ? ' on' : ''}`} onClick={() => pick(f)}>
          <button className="link when" onClick={e => { e.stopPropagation(); pick(f); }}>{mmss(f.time_s)}</button>
          <span className="what"><span className="dot" style={{ background: color(f.dancer), marginRight: 8 }} /><b>{label(f.dancer)}</b>
            <span className="muted"> for {f.end_beat - f.start_beat + 1} beats</span></span>
          <span className="pill neg">{Math.abs(f.offset_ms)} ms {f.offset_ms > 0 ? 'late' : 'early'}</span>
        </li>
      ))}
      {!res.flags.length && <li className="faint">No flagged moments: every dancer stayed within 120 ms of the crew.</li>}
      {res.flags.length > shown.length && <li className="faint small" style={{ display: 'block', padding: '8px 12px' }}>The {shown.length} biggest of {res.flags.length} flagged moments; the rest are on the strip.</li>}
    </ul>
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
    g.font = `600 ${Math.max(12, c.height / 32)}px Inter, system-ui`;
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
      g.save(); g.lineWidth = Math.max(3, c.height / 160); g.strokeStyle = 'rgba(0,0,0,0.75)'; g.lineJoin = 'round';
      g.strokeText(label(d), b[0], b[1] - 6); g.restore();
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
    g.fillStyle = '#0a0a0a';
    g.fillRect(0, 0, W, H);
    const s = Math.min(W / (bounds.x1 - bounds.x0), H / Math.max(1, bounds.y1 - bounds.y0));
    const px = (p: number[]) => [(p[0] - bounds.x0) * s + (W - (bounds.x1 - bounds.x0) * s) / 2, (p[1] - bounds.y0) * s + (H - (bounds.y1 - bounds.y0) * s) / 2];
    const t = frame / res.fps;
    let b = -1;
    for (let i = 0; i < res.beats.length && res.beats[i] <= t; i++) b = i;
    const prevFrame = b > 0 ? Math.round(res.beats[b - 1] * res.fps) : -1;
    g.font = '400 12px Inter, system-ui';
    g.fillStyle = '#949494';
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
        g.strokeStyle = '#e5484d'; g.lineWidth = 2.5;
        g.beginPath(); g.arc(x, y, 12, 0, Math.PI * 2); g.stroke();
      }
    }
  });
  return <canvas ref={ref} className="formation" aria-label="Formation map" />;
}

function FixSwap({ ids, label, t, busy, onSwap }: { ids: string[]; label: (d: string) => string; t: number; busy: boolean; onSwap: (a: string, b: string) => void }) {
  const [a, setA] = useState(ids[0] ?? '');
  const [b, setB] = useState(ids[1] ?? '');
  return (
    <details className="tool">
      <summary>Fix swapped colors</summary>
      <div className="body">
      <p className="muted">After two dancers cross, their colors can swap. Pause where it happens and swap them from there.</p>
      <div className="row">
        <select value={a} onChange={e => setA(e.target.value)} aria-label="First dancer">{ids.map(d => <option key={d} value={d}>{label(d)}</option>)}</select>
        <span>and</span>
        <select value={b} onChange={e => setB(e.target.value)} aria-label="Second dancer">{ids.map(d => <option key={d} value={d}>{label(d)}</option>)}</select>
        <button disabled={busy || a === b} onClick={() => onSwap(a, b)}>{busy ? 'Fixing…' : `Swap from ${mmss(t)}`}</button>
      </div>
      </div>
    </details>
  );
}

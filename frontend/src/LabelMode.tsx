import { RefObject, useEffect, useState } from 'react';
import { api, Flag, HandLabel, LabelAgreement } from './api';

const TOLERANCE_S = 0.5; // same as backend/pipeline/labels.py

const mmss = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`;
const pct = (v: number | null) => (v === null ? '–' : `${Math.round(v * 100)}%`);

// Evaluation helper (PRD: hand labels on 3 clips). Watch at quarter speed and press L or E the moment a dancer is
// visibly late or early; the app's flags are scored against these labels.
export default function LabelMode({ id, ids, flags, beats, label, color, video }: {
  id: string; ids: string[]; flags: Flag[]; beats: number[]; label: (d: string) => string; color: (d: string) => string;
  video: RefObject<HTMLVideoElement>;
}) {
  const [open, setOpen] = useState(false);
  const [labels, setLabels] = useState<HandLabel[]>([]);
  const [agree, setAgree] = useState<LabelAgreement | null>(null);
  const [dancer, setDancer] = useState(ids[0] ?? '');
  const [slow, setSlow] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open) api.labels(id).then(r => { setLabels(r.labels); setAgree(r.agreement); }, e => setErr(e.message));
  }, [open, id]);

  const save = async (next: HandLabel[]) => {
    setLabels(next);
    try { setAgree((await api.saveLabels(id, next)).agreement); setErr(''); } catch (x) { setErr((x as Error).message); }
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, select, textarea')) return;
      const k = e.key.toLowerCase();
      if (/^[1-9]$/.test(k) && ids[Number(k) - 1]) setDancer(ids[Number(k) - 1]);
      else if ((k === 'l' || k === 'e') && video.current && dancer) {
        const t = Math.round(video.current.currentTime * 100) / 100;
        const next: HandLabel = { dancer, time_s: t, kind: k === 'l' ? 'late' : 'early' };
        save([...labels, next].sort((a, b) => a.time_s - b.time_s));
      }
    };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  });

  // Verdict on one of the app's flags: Real adds a late/early label at its time, Wrong adds a "wrong" one.
  const verdictOf = (f: Flag) => labels.find(l => l.dancer === f.dancer &&
    l.time_s >= beats[f.start_beat] - TOLERANCE_S && l.time_s <= beats[f.end_beat] + TOLERANCE_S &&
    (l.kind === 'wrong' || l.kind === (f.offset_ms > 0 ? 'late' : 'early')));
  const judge = (f: Flag, kind: HandLabel['kind']) => {
    const rest = labels.filter(l => l !== verdictOf(f));
    save([...rest, { dancer: f.dancer, time_s: f.time_s, kind }].sort((a, b) => a.time_s - b.time_s));
  };

  const toggleSlow = () => {
    if (!video.current) return;
    video.current.playbackRate = slow ? 1 : 0.25;
    setSlow(!slow);
  };

  return (
    <details className="tool" onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Hand-label this clip</summary>
      <div className="body">
      <p className="muted">Pick a dancer (or press 1–{Math.min(9, ids.length)}), play at quarter speed, and press <kbd>L</kbd> when they're visibly late or <kbd>E</kbd> when early.</p>
      <div className="row">
        <button onClick={toggleSlow}>{slow ? 'Normal speed' : 'Quarter speed'}</button>
        <select value={dancer} onChange={e => setDancer(e.target.value)} aria-label="Dancer to label">
          {ids.map((d, k) => <option key={d} value={d}>{k + 1}. {label(d)}</option>)}
        </select>
      </div>
      {err && <p className="error">{err}</p>}
      {agree && (agree.labels > 0 || agree.flags_wrong > 0) && (
        <p className="small">App flags judged real: <b>{agree.flags_agreed}</b>, wrong: <b>{agree.flags_wrong}</b>, not yet judged:
          {' '}<b>{agree.flags - agree.flags_agreed - agree.flags_wrong}</b> (precision {pct(agree.precision)}) ·
          {' '}your labels the app caught: <b>{agree.labels_caught}/{agree.labels}</b> ({pct(agree.recall)})</p>
      )}
      {flags.length > 0 && <p className="muted" style={{ marginBottom: 4 }}>The app's flags. Jump to each, watch at quarter speed, judge it.</p>}
      <ul className="flags" style={{ marginTop: 0 }}>
        {flags.map((f, i) => {
          const v = verdictOf(f)?.kind;
          return (
            <li key={i}>
              <button className="link when" onClick={() => { if (video.current) video.current.currentTime = Math.max(f.time_s - 1, 0); }}>{mmss(f.time_s)}</button>
              <span className="what"><span className="dot" style={{ background: color(f.dancer), marginRight: 8 }} />{label(f.dancer)} {Math.abs(f.offset_ms)} ms {f.offset_ms > 0 ? 'late' : 'early'}{f.moving ? <span className="muted"> · crew moving</span> : null}</span>
              <span className="row" style={{ gap: 6 }}>
                <button className={v && v !== 'wrong' ? '' : 'ghost'} onClick={() => judge(f, f.offset_ms > 0 ? 'late' : 'early')}>Real</button>
                <button className={v === 'wrong' ? '' : 'ghost'} onClick={() => judge(f, 'wrong')}>Wrong</button>
              </span>
            </li>
          );
        })}
      </ul>
      <ul className="flags" style={{ marginTop: 0 }}>
        {labels.map((l, i) => (
          <li key={i}>
            <button className="link when" onClick={() => { if (video.current) video.current.currentTime = l.time_s; }}>{mmss(l.time_s)}</button>
            <span className="what"><span className="dot" style={{ background: color(l.dancer), marginRight: 8 }} />{label(l.dancer)} {l.kind}</span>
            <button className="ghost" aria-label="Remove label" onClick={() => save(labels.filter((_, j) => j !== i))}>Remove</button>
          </li>
        ))}
        {!labels.length && <li className="faint">No labels yet.</li>}
      </ul>
      </div>
    </details>
  );
}

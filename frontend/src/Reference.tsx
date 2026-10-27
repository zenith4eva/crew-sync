import { useEffect, useState } from 'react';
import { api, Results, Status } from './api';

type Props = {
  id: string; res: Results; ids: string[];
  label: (d: string) => string; color: (d: string) => string;
  onResults: (r: Results) => void;
};

// Score against a leader's or official take instead of the crew median. The reference video is deleted on the
// server right after tracking; only the match and alignment are shown here, never its footage.
export default function ReferencePanel({ id, res, ids, label, color, onResults }: Props) {
  const [ref, setRef] = useState<Status['reference']>(null);
  const [file, setFile] = useState<File | null>(null);
  const [mirror, setMirror] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    let stop = false, timer = 0;
    const poll = async () => {
      const st = await api.status(id).catch(() => null);
      if (stop || !st) return;
      setRef(st.reference ?? null);
      if (st.reference?.state === 'queued' || st.reference?.state === 'running' || st.reference?.state === 'scoring') timer = window.setTimeout(poll, 2000);
      else if (st.reference?.state === 'done' && !res.reference) onResults(await api.results(id));
    };
    poll();
    return () => { stop = true; clearTimeout(timer); };
  }, [id, ref?.state]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setErr('');
    try { await fn(); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  }

  const upload = () => run(async () => {
    const form = new FormData();
    form.append('video', file!);
    form.append('mirror', String(mirror));
    setRef((await api.addReference(id, form)).reference ?? null);
  });

  const refLabel = (j: string) => `Ref ${(res.reference?.ref_order.indexOf(j) ?? -1) + 1}`;

  return (
    <details className="tool" open={!!ref}>
      <summary>Score against a reference take{ref?.state === 'done' ? <span className="pill pos">On</span> : null}</summary>
      <div className="body">
      {err && <p className="error" role="alert">{err}</p>}

      {(ref?.state === 'queued' || ref?.state === 'running' || ref?.state === 'scoring') && (
        <><div className="progress" aria-hidden><div /></div><p className="muted">Tracking and aligning the reference…</p></>
      )}

      {(!ref || ref.state === 'failed') && (
        <div className="ref-form">
          {ref?.state === 'failed' && <p className="error">{ref.error}</p>}
          <p className="muted">Score against the leader's or the official video instead of the crew. It's used only for scoring: the video is deleted right after tracking and never shown or shared.</p>
          <input type="file" accept="video/mp4,video/quicktime,.mp4,.mov" aria-label="Reference video" onChange={e => setFile(e.target.files?.[0] ?? null)} />
          <label className="check"><input type="checkbox" checked={mirror} onChange={e => setMirror(e.target.checked)} /><span>Reference is mirrored (a mirror-mode practice video)</span></label>
          <button disabled={!file || busy} onClick={upload}>{busy ? 'Uploading…' : 'Score against reference'}</button>
        </div>
      )}

      {ref?.state === 'done' && res.reference && (
        <div className="ref-form">
          <p className="muted">
            Timing and positions are measured against each dancer's match in the reference.
{` Aligned by audio (offset ${res.reference.lag_s.toFixed(2)} s).`}
          </p>
          <label className="check">
            <input type="checkbox" checked={res.reference.mirror} disabled={busy}
              onChange={e => run(async () => onResults(await api.referenceSettings(id, { mirror: e.target.checked })))} />
            <span>Reference is mirrored</span>
          </label>
          <table className="dancers">
            <thead><tr><th>Dancer</th><th>Matches</th></tr></thead>
            <tbody>
              {ids.map(d => (
                <tr key={d}>
                  <td><span className="name-cell"><span className="dot" style={{ background: color(d) }} />{label(d)}</span></td>
                  <td>
                    <select value={res.reference!.matches[d] ?? ''} disabled={busy} aria-label={`Reference match for ${label(d)}`}
                      onChange={e => run(async () => onResults(await api.referenceSettings(id, { matches: { ...res.reference!.matches, [d]: e.target.value } })))}>
                      {!res.reference!.matches[d] && <option value="">No match</option>}
                      {res.reference!.ref_order.map(j => <option key={j} value={j}>{refLabel(j)}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="faint small">Ref numbers count left to right as the reference opens{res.reference.mirror ? ' (after mirroring)' : ''}.</p>
          <button className="ghost" disabled={busy} onClick={() => run(async () => { onResults(await api.removeReference(id)); setRef(null); })}>Remove reference</button>
        </div>
      )}
      </div>
    </details>
  );
}

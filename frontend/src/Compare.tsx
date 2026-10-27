import { useEffect, useState } from 'react';
import { api, Results, Status } from './api';

type Take = { st: Status; res: Results };
const r = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.round(v));

function Delta({ before, after }: { before: number | null; after: number | null }) {
  if (before === null || after === null) return <span className="muted">–</span>;
  const d = after - before;
  return <span className={d > 0 ? 'up' : d < 0 ? 'down' : 'muted'}>{d > 0 ? '+' : ''}{d}</span>;
}

export default function Compare({ before, after }: { before: string; after: string }) {
  const [takes, setTakes] = useState<[Take, Take] | null>(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    const load = async (id: string): Promise<Take> => ({ st: await api.status(id), res: await api.results(id) });
    Promise.all([load(before), load(after)]).then(t => setTakes(t as [Take, Take]), e => setErr(e.message));
  }, [before, after]);

  if (err) return <div className="card"><p className="error">{err}</p></div>;
  if (!takes) return <div className="card muted">Loading takes…</div>;
  const [a, b] = takes;

  // Match dancers across takes by the names the crew gave them; SAM ids differ between videos.
  const byName = (t: Take) => new Map(Object.entries(t.st.names).map(([id, n]) => [n.trim().toLowerCase(), id]));
  const na = byName(a), nb = byName(b);
  const names = [...na.keys()].filter(n => nb.has(n));
  const display = (n: string) => a.st.names[na.get(n)!];

  return (
    <div className="results">
      <section className="card compare-hero">
        <div><div className="eyebrow">Before</div><div className="big muted-num">{r(a.res.crew_score) ?? '–'}</div></div>
        <div className="arrow" aria-hidden>→</div>
        <div><div className="eyebrow">After</div><div className="big">{r(b.res.crew_score) ?? '–'}</div></div>
        <div className="delta-big"><Delta before={r(a.res.crew_score)} after={r(b.res.crew_score)} /></div>
        <p className="muted">Flagged moments: {a.res.flags.length} → {b.res.flags.length}</p>
      </section>

      <section className="card">
        <h3>Dancer by dancer</h3>
        {names.length ? (
          <table className="dancers">
            <thead><tr><th>Name</th><th>Before</th><th>After</th><th>Change</th><th>Timing</th><th>Formation</th></tr></thead>
            <tbody>
              {names.map(n => {
                const da = a.res.dancers[na.get(n)!], db = b.res.dancers[nb.get(n)!];
                return (
                  <tr key={n}>
                    <td>{display(n)}</td>
                    <td>{r(da?.score) ?? '–'}</td>
                    <td><b>{r(db?.score) ?? '–'}</b></td>
                    <td><Delta before={r(da?.score)} after={r(db?.score)} /></td>
                    <td><Delta before={r(da?.timing)} after={r(db?.timing)} /></td>
                    <td><Delta before={r(da?.formation)} after={r(db?.formation)} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <p className="muted">Give dancers the same names in both takes to compare them one by one.</p>}
        <div className="row" style={{ marginTop: 12 }}>
          <a href={`#job=${before}`}>Open before</a>
          <a href={`#job=${after}`}>Open after</a>
        </div>
      </section>
    </div>
  );
}

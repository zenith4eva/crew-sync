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

  if (err) return <div className="card narrow"><p className="error">{err}</p></div>;
  if (!takes) return <div className="card narrow muted">Loading takes…</div>;
  const [a, b] = takes;

  // Match dancers across takes by the names the crew gave them; SAM ids differ between videos.
  const byName = (t: Take) => new Map(Object.entries(t.st.names).map(([id, n]) => [n.trim().toLowerCase(), id]));
  const na = byName(a), nb = byName(b);
  const names = [...na.keys()].filter(n => nb.has(n));
  const display = (n: string) => a.st.names[na.get(n)!];

  return (
    <div className="arrive">
      <div className="title-row">
        <div>
          <h1>Compare takes</h1>
          <p className="lede">Crew Sync Score <b>{r(a.res.crew_score) ?? '–'} → {r(b.res.crew_score) ?? '–'}</b>, from the earlier take to the later one.</p>
        </div>
      </div>
      <section className="kpis compare-kpis" aria-label="Summary">
        <div className="kpi"><span className="kpi-label">Before</span><span className="kpi-value muted">{r(a.res.crew_score) ?? '–'}</span></div>
        <div className="kpi"><span className="kpi-label">After</span><span className="kpi-value lead">{r(b.res.crew_score) ?? '–'}</span></div>
        <div className="kpi"><span className="kpi-label">Change</span><span className="kpi-value"><Delta before={r(a.res.crew_score)} after={r(b.res.crew_score)} /></span></div>
        <div className="kpi"><span className="kpi-label">Flagged moments</span><span className="kpi-value">{a.res.flags.length} → {b.res.flags.length}</span></div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Dancer by dancer</h2><span className="end faint small">Matched by name across the two takes</span></div>
        {names.length ? (
          <table className="dancers">
            <thead><tr><th>Name</th><th className="num">Before</th><th className="num">After</th><th className="num">Change</th><th className="num">Timing</th><th className="num">Formation</th></tr></thead>
            <tbody>
              {names.map(n => {
                const da = a.res.dancers[na.get(n)!], db = b.res.dancers[nb.get(n)!];
                return (
                  <tr key={n}>
                    <td>{display(n)}</td>
                    <td className="num muted">{r(da?.score) ?? '–'}</td>
                    <td className="num"><b>{r(db?.score) ?? '–'}</b></td>
                    <td className="num"><Delta before={r(da?.score)} after={r(db?.score)} /></td>
                    <td className="num"><Delta before={r(da?.timing)} after={r(db?.timing)} /></td>
                    <td className="num"><Delta before={r(da?.formation)} after={r(db?.formation)} /></td>
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

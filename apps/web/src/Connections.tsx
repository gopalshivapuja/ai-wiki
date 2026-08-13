import { lazy, Suspense, useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { docPath, getNeighbourhood } from './api';
import { TYPE_COLORS } from './graphColors';
import { useAsync } from './hooks';

// vis-network is ~600KB. Fetched when a map is opened, never for a reader who just reads.
const GraphView = lazy(() => import('./GraphView').then((m) => ({ default: m.GraphView })));

/** The graph around one note.
 *
 * This replaced a whole-wiki graph page. At 400 notes and 1,100 edges that view was a
 * hairball: it looked impressive and answered nothing. The question a reader actually has
 * standing on a note is "what surrounds this idea?", which is a neighbourhood, not an atlas.
 */
export function Connections({ slug }: { slug: string }) {
  const [hops, setHops] = useState(1);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  // Not fetched until opened: vis-network and the graph query are both wasted on a reader
  // who only wanted to read the note.
  const { data, loading, error } = useAsync(
    () => (open ? getNeighbourhood(slug, hops) : Promise.resolve(null)),
    [slug, hops, open],
  );
  const onSelect = useCallback((s: string) => navigate(docPath(s)), [navigate]);

  const others = (data?.nodes.length ?? 1) - 1;
  const types = [...new Set((data?.nodes ?? []).map((n) => n.type))].sort();

  return (
    <section className="panel connections">
      <div className="row space-between wrap">
        <h2>
          Connections{data && <span className="muted small"> — {others} nearby</span>}
        </h2>
        <div className="row gap">
          {open && (
            <div className="hop-toggle" role="group" aria-label="How far to look">
              {[1, 2].map((h) => (
                <button
                  key={h}
                  className={`ghost small${hops === h ? ' active' : ''}`}
                  aria-pressed={hops === h}
                  onClick={() => setHops(h)}
                >
                  {h} hop{h > 1 ? 's' : ''}
                </button>
              ))}
            </div>
          )}
          <button className="ghost small" onClick={() => setOpen((o) => !o)}>
            {open ? 'Hide' : 'Show map'}
          </button>
        </div>
      </div>

      {!open && (
        <p className="muted small">
          A map of the notes around this one — what it links to, and what links to it.
        </p>
      )}

      {open && (
        <>
          {loading && <p className="muted small">Drawing…</p>}
          {error && <p className="error">{error}</p>}
          {data && others === 0 && (
            <p className="muted small">
              Nothing links to this note yet, and it links nowhere. Mention it from another
              note to connect it.
            </p>
          )}
          {data && others > 0 && (
            <>
              <Suspense fallback={<p className="muted small">Loading map…</p>}>
                <GraphView data={data} onSelect={onSelect} focusSlug={slug} />
              </Suspense>
              <div className="row space-between wrap">
                <div className="legend">
                  {types.map((t) => (
                    <span key={t} className="legend-item">
                      <span
                        className="legend-dot"
                        style={{ background: TYPE_COLORS[t] || TYPE_COLORS.page }}
                      />
                      {t}
                    </span>
                  ))}
                </div>
                <p className="muted small">
                  Hover to isolate, click to open.
                  {data.truncated && ' Showing the best-connected neighbours only.'}
                </p>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

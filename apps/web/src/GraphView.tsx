import { useEffect, useMemo, useRef } from 'react';
import { Network } from 'vis-network/standalone';
import type { GraphData } from './api';

export const TYPE_COLORS: Record<string, string> = {
  zettel: '#6ea8fe',
  concept: '#3dd68c',
  entity: '#f0ad4e',
  literature: '#c77dff',
  moc: '#ff6b6b',
  synthesis: '#adb5bd',
  index: '#ffd166',
  page: '#9b9ba8',
  web: '#7f8c9a',
  pdf: '#7f8c9a',
  youtube: '#7f8c9a',
  audio: '#7f8c9a',
  arxiv: '#7f8c9a',
  note: '#7f8c9a',
};

interface Props {
  data: GraphData;
  onSelect?: (slug: string) => void;
  focusSlug?: string;
  hiddenTypes?: Set<string>;
}

const DIM = 'rgba(140,140,150,0.18)';

export function GraphView({ data, onSelect, focusSlug, hiddenTypes }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  // Held in a ref so a new inline callback from the parent does not rebuild the network,
  // which would restart physics and throw away the user's zoom and pan.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const visible = useMemo(() => {
    const hidden = hiddenTypes ?? new Set<string>();
    const nodes = data.nodes.filter((n) => !hidden.has(n.type));
    const keep = new Set(nodes.map((n) => n.slug));
    return { nodes, edges: data.edges.filter((e) => keep.has(e.source) && keep.has(e.target)) };
  }, [data, hiddenTypes]);

  useEffect(() => {
    if (!ref.current) return;

    const baseColor = (t: string) => TYPE_COLORS[t] || TYPE_COLORS.page;
    const nodes = visible.nodes.map((n) => ({
      id: n.slug,
      label: n.title.length > 26 ? n.title.slice(0, 24) + '…' : n.title,
      title: `${n.title}\n${n.type} · ${n.link_count} links`,
      color: baseColor(n.type),
      size: Math.min(38, 11 + n.link_count * 1.8),
    }));
    const edges = visible.edges.map((e) => ({ from: e.source, to: e.target, arrows: 'to' }));

    const network = new Network(
      ref.current,
      { nodes, edges },
      {
        physics: {
          stabilization: { iterations: 140 },
          barnesHut: { gravitationalConstant: -9000, springLength: 130 },
        },
        interaction: { hover: true, tooltipDelay: 120 },
        nodes: {
          font: { color: getComputedStyle(document.body).color, size: 12 },
          borderWidth: 0,
          shape: 'dot',
        },
        edges: {
          color: { color: DIM, highlight: '#6ea8fe', hover: '#6ea8fe' },
          smooth: { enabled: true, type: 'continuous', roundness: 0.4 },
          width: 0.6,
        },
      },
    );

    // Hovering a node dims everything that is not its immediate neighbourhood, which is the
    // only practical way to read a dense graph.
    const neighbours = (slug: string) => {
      const set = new Set<string>([slug]);
      for (const e of visible.edges) {
        if (e.source === slug) set.add(e.target);
        if (e.target === slug) set.add(e.source);
      }
      return set;
    };
    const emphasise = (slug: string | null) => {
      const near = slug ? neighbours(slug) : null;
      network.setData({
        nodes: nodes.map((n) => ({
          ...n,
          color: !near || near.has(String(n.id)) ? n.color : DIM,
          font: near && !near.has(String(n.id)) ? { color: DIM } : undefined,
        })),
        edges: edges.map((e) => ({
          ...e,
          color: !near || (near.has(e.from) && near.has(e.to)) ? undefined : DIM,
        })),
      });
    };

    network.on('hoverNode', (p) => emphasise(String(p.node)));
    network.on('blurNode', () => emphasise(null));
    network.on('click', (p) => {
      if (p.nodes.length) onSelectRef.current?.(String(p.nodes[0]));
    });

    networkRef.current = network;
    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [visible]);

  useEffect(() => {
    const network = networkRef.current;
    if (!focusSlug || !network) return;
    if (!visible.nodes.some((n) => n.slug === focusSlug)) return;
    network.selectNodes([focusSlug]);
    network.focus(focusSlug, { scale: 1.3, animation: true });
  }, [focusSlug, visible]);

  return <div ref={ref} className="graph-container" />;
}

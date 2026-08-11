import { useEffect, useRef } from 'react';
import { Network } from 'vis-network/standalone';
import type { GraphData } from './api';

const TYPE_COLORS: Record<string, string> = {
  zettel: '#6ea8fe',
  concept: '#3dd68c',
  entity: '#f0ad4e',
  literature: '#c77dff',
  moc: '#ff6b6b',
  synthesis: '#adb5bd',
  page: '#9b9ba8',
};

interface Props {
  data: GraphData;
  onSelect?: (slug: string) => void;
  focusSlug?: string;
}

export function GraphView({ data, onSelect, focusSlug }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);

  useEffect(() => {
    if (!ref.current) return;

    const nodes = data.nodes.map((n) => ({
      id: n.slug,
      label: n.title.length > 24 ? n.title.slice(0, 22) + '…' : n.title,
      title: `${n.title}\n(${n.type}, ${n.link_count} links)`,
      color: TYPE_COLORS[n.type] || TYPE_COLORS.page,
      size: Math.min(40, 12 + n.link_count * 2),
    }));

    const edges = data.edges.map((e) => ({ from: e.source, to: e.target, arrows: 'to' }));

    const network = new Network(
      ref.current,
      { nodes, edges },
      {
        physics: { stabilization: { iterations: 120 }, barnesHut: { gravitationalConstant: -8000 } },
        interaction: { hover: true, tooltipDelay: 100 },
        edges: { color: { color: '#3a3a45', highlight: '#6ea8fe' }, smooth: { enabled: true, type: 'continuous', roundness: 0.5 } },
      }
    );

    network.on('click', (params) => {
      if (params.nodes.length && onSelect) {
        onSelect(String(params.nodes[0]));
      }
    });

    networkRef.current = network;
    return () => network.destroy();
  }, [data, onSelect]);

  useEffect(() => {
    if (focusSlug && networkRef.current) {
      networkRef.current.selectNodes([focusSlug]);
      networkRef.current.focus(focusSlug, { scale: 1.2, animation: true });
    }
  }, [focusSlug]);

  return <div ref={ref} className="graph-container" />;
}

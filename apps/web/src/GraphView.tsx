import { useEffect, useRef } from 'react';
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
};

interface Props {
  data: GraphData;
  onSelect?: (slug: string) => void;
  focusSlug?: string;
}

export function GraphView({ data, onSelect, focusSlug }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  // Held in a ref so a new inline callback from the parent does not rebuild the network,
  // which would restart physics and throw away the user's zoom and pan.
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

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
        physics: {
          stabilization: { iterations: 120 },
          barnesHut: { gravitationalConstant: -8000 },
        },
        interaction: { hover: true, tooltipDelay: 100, navigationButtons: false },
        nodes: { font: { color: '#e8e8ed', size: 13 }, borderWidth: 0 },
        edges: {
          color: { color: '#3a3a45', highlight: '#6ea8fe' },
          smooth: { enabled: true, type: 'continuous', roundness: 0.5 },
          width: 0.5,
        },
      },
    );

    network.on('click', (params) => {
      if (params.nodes.length) onSelectRef.current?.(String(params.nodes[0]));
    });

    networkRef.current = network;
    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [data]);

  useEffect(() => {
    const network = networkRef.current;
    if (!focusSlug || !network) return;
    if (!data.nodes.some((n) => n.slug === focusSlug)) return;
    network.selectNodes([focusSlug]);
    network.focus(focusSlug, { scale: 1.2, animation: true });
  }, [focusSlug, data]);

  return <div ref={ref} className="graph-container" />;
}

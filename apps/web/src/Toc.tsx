import { useMemo } from 'react';

/** Slug used for heading anchors. Mirrors what `Markdown` puts on each heading. */
export function headingId(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-');
}

interface Heading {
  id: string;
  text: string;
  level: number;
}

/** Headings taken from the markdown source, ignoring fenced code. */
export function extractHeadings(markdown: string): Heading[] {
  const withoutCode = markdown.replace(/```[\s\S]*?```/g, '');
  const out: Heading[] = [];
  for (const m of withoutCode.matchAll(/^(#{2,3})\s+(.+)$/gm)) {
    const text = m[2].replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_x, t, l) => l || t).trim();
    out.push({ id: headingId(text), text, level: m[1].length });
  }
  return out;
}

/** A contents list for long documents. Renders nothing when there is little to navigate. */
export function Toc({ markdown }: { markdown: string }) {
  const headings = useMemo(() => extractHeadings(markdown), [markdown]);
  if (headings.length < 3) return null;

  return (
    <section className="toc">
      <h3>On this page</h3>
      <nav>
        {headings.map((h) => (
          <a
            key={h.id + h.text}
            href={`#${h.id}`}
            className={`level-${h.level}`}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey) return;
              e.preventDefault();
              document.getElementById(h.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }}
          >
            {h.text}
          </a>
        ))}
      </nav>
    </section>
  );
}

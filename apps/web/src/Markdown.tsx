import React, { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
// Loaded with this component, so the ~24KB of KaTeX CSS and its fonts stay out of the
// initial page load.
import 'katex/dist/katex.min.css';
import { useNavigate } from 'react-router-dom';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import { docPath, type WikiLink } from './api';

interface Props {
  content: string;
  /** Resolved link targets from the API, used to grey out notes that do not exist yet. */
  links?: WikiLink[];
}

const WIKI_PREFIX = 'wiki:';

export function Markdown({ content, links }: Props) {
  const navigate = useNavigate();

  const resolved = useMemo(() => {
    const map = new Map<string, WikiLink>();
    for (const l of links || []) map.set(l.target.trim(), l);
    return map;
  }, [links]);

  const components = useMemo(
    () => ({
      a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
        if (!href?.startsWith(WIKI_PREFIX)) {
          return (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          );
        }
        const target = decodeURIComponent(href.slice(WIKI_PREFIX.length));
        const link = resolved.get(target);
        // Unknown targets render as red links rather than navigating to a 404.
        if (link && !link.exists) {
          // Unwritten notes are an invitation, not a dead end.
          return (
            <a
              href={`/edit/new?title=${encodeURIComponent(target)}`}
              className="red-link"
              title="This note does not exist yet — click to write it"
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                navigate(`/edit/new?title=${encodeURIComponent(target)}`);
              }}
            >
              {children}
            </a>
          );
        }
        const slug = link?.slug || target;
        const to = docPath(slug);
        return (
          <a
            href={to}
            onClick={(e) => {
              // Let the browser handle modified clicks so open-in-new-tab keeps working.
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
              e.preventDefault();
              navigate(to);
            }}
          >
            {children}
          </a>
        );
      },
    }),
    [navigate, resolved],
  );

  const processed = useMemo(() => preprocessWikilinks(content), [content]);

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}

export function preprocessWikilinks(text: string): string {
  const withoutFrontmatter = text.replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '');
  return withoutFrontmatter.replace(
    /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
    (_match, target: string, label: string | undefined) => {
      const clean = target.trim();
      const display = label || clean.replace(/-/g, ' ');
      return `[${display}](${WIKI_PREFIX}${encodeURIComponent(clean)})`;
    },
  );
}

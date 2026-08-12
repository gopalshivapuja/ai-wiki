import React, { useMemo } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
// Loaded with this component, so the ~24KB of KaTeX CSS and its fonts stay out of the
// initial page load.
import 'katex/dist/katex.min.css';
import { useNavigate } from 'react-router-dom';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import { docPath, type WikiLink } from './api';
import { headingId } from './Toc';

interface Props {
  content: string;
  /** Resolved link targets from the API, used to grey out notes that do not exist yet. */
  links?: WikiLink[];
  /** Slug of the document being rendered, so links back to it render as plain text. */
  selfSlug?: string;
}

const WIKI_PREFIX = 'wiki:';

/** Flatten a heading's children back to plain text for its anchor id. */
function textOf(node: React.ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (typeof node === 'object' && 'props' in (node as never)) {
    return textOf((node as { props: { children?: React.ReactNode } }).props.children);
  }
  return '';
}

/** Keep our internal scheme; sanitise everything else as react-markdown normally would.
 *
 * Without this, react-markdown's defaultUrlTransform drops any scheme outside
 * http/https/mailto/xmpp/irc — so every `wiki:` href became "", which the browser resolves
 * to the current page. Combined with target="_blank" on the fallback branch, clicking any
 * wikilink opened a new tab showing the page you were already on.
 */
function urlTransform(url: string): string {
  return url.startsWith(WIKI_PREFIX) ? url : defaultUrlTransform(url);
}

export function Markdown({ content, links, selfSlug }: Props) {
  const navigate = useNavigate();

  const resolved = useMemo(() => {
    const map = new Map<string, WikiLink>();
    for (const l of links || []) map.set(l.target.trim(), l);
    return map;
  }, [links]);

  const components = useMemo(
    () => ({
      // Headings carry ids so the contents list can jump to them.
      h2: ({ children }: { children?: React.ReactNode }) => (
        <h2 id={headingId(textOf(children))}>{children}</h2>
      ),
      h3: ({ children }: { children?: React.ReactNode }) => (
        <h3 id={headingId(textOf(children))}>{children}</h3>
      ),
      a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
        if (!href?.startsWith(WIKI_PREFIX)) {
          // Genuinely external: a new tab keeps your place in the wiki. Cmd+click still
          // works, and the browser handles it.
          return (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          );
        }

        const target = decodeURIComponent(href.slice(WIKI_PREFIX.length));
        const link = resolved.get(target);

        // A note linking to itself is a no-op, not a navigation.
        if (selfSlug && (link?.slug === selfSlug || target === selfSlug)) {
          return <span className="self-link">{children}</span>;
        }

        // Unwritten notes are an invitation, not a dead end.
        if (link && !link.exists) {
          const to = `/edit/new?title=${encodeURIComponent(target)}`;
          return (
            <a
              href={to}
              className="red-link"
              title="This note does not exist yet — click to write it"
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                e.preventDefault();
                navigate(to);
              }}
            >
              {children}
            </a>
          );
        }

        const to = docPath(link?.slug || target);
        return (
          <a
            href={to}
            onClick={(e) => {
              // Let the browser handle modified clicks so open-in-new-tab keeps working.
              if (e.metaKey || e.ctrlKey || e.shiftKey) return;
              e.preventDefault();
              navigate(to);
            }}
          >
            {children}
          </a>
        );
      },
    }),
    [navigate, resolved, selfSlug],
  );

  const processed = useMemo(() => preprocessWikilinks(content), [content]);

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        urlTransform={urlTransform}
        components={components}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}

/** Rewrite [[wikilinks]] into markdown links carrying our internal scheme.
 *
 * Mermaid code fences are skipped: their node labels can contain [[…]] which is inert
 * diagram text, not a link.
 */
export function preprocessWikilinks(text: string): string {
  const withoutFrontmatter = text.replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '');
  return withoutFrontmatter.replace(/```[\s\S]*?```|\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (
    match,
    target: string | undefined,
    label: string | undefined,
  ) => {
    if (target === undefined) return match; // a fenced code block — leave it alone
    const clean = target.trim();
    const display = label || clean.replace(/-/g, ' ');
    return `[${display}](${WIKI_PREFIX}${encodeURIComponent(clean)})`;
  });
}

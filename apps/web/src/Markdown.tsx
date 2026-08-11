import React from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

interface Props {
  content: string;
}

export function Markdown({ content }: Props) {
  const navigate = useNavigate();

  const components = {
    a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
      if (href?.startsWith('wiki:')) {
        const slug = href.replace('wiki:', '');
        return (
          <a
            href={`/wiki/${slug}`}
            onClick={(e) => {
              e.preventDefault();
              navigate(`/wiki/${slug}`);
            }}
          >
            {children}
          </a>
        );
      }
      return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
    },
  };

  const processed = preprocessWikilinks(content);

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

function preprocessWikilinks(text: string): string {
  // Remove YAML frontmatter for display
  const withoutFm = text.replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '');
  // Convert [[slug|Title]] or [[slug]] to markdown links
  return withoutFm.replace(
    /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
    (_, slug, title) => `[${title || slug.replace(/-/g, ' ')}](wiki:${slug.trim()})`
  );
}

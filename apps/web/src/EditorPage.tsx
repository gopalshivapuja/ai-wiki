import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  createDoc,
  deleteDoc,
  docPath,
  getDoc,
  listDocs,
  updateDoc,
  type WikiLink,
} from './api';
import { useAsync } from './hooks';
import { Markdown } from './Markdown';

const NOTE_TYPES = ['zettel', 'concept', 'entity', 'moc', 'synthesis', 'literature', 'page'];

interface Suggestion {
  slug: string;
  title: string;
}

export function EditorPage() {
  const { slug = '' } = useParams<{ slug: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const isNew = slug === 'new';

  const [title, setTitle] = useState(params.get('title') || '');
  const [body, setBody] = useState('');
  const [type, setType] = useState('zettel');
  const [tags, setTags] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [links, setLinks] = useState<WikiLink[]>([]);

  const all = useAsync(() => listDocs(), []);
  const existing = useAsync(async () => (isNew ? null : getDoc(slug)), [slug, isNew]);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [autocomplete, setAutocomplete] = useState<{ query: string; start: number } | null>(null);
  const [activeSuggestion, setActiveSuggestion] = useState(0);

  useEffect(() => {
    const doc = existing.data;
    if (!doc) return;
    setTitle(doc.title);
    setBody(doc.body);
    setType(doc.type);
    setTags((doc.tags || []).join(', '));
    setLinks(doc.links || []);
  }, [existing.data]);

  // Warn before losing unsaved edits to a refresh or a closed tab.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const suggestions: Suggestion[] = useMemo(() => {
    if (!autocomplete) return [];
    const q = autocomplete.query.toLowerCase();
    return (all.data?.documents ?? [])
      .filter((d) => d.title.toLowerCase().includes(q) || d.slug.includes(q))
      .slice(0, 8)
      .map((d) => ({ slug: d.slug, title: d.title }));
  }, [autocomplete, all.data]);

  const onBodyChange = (value: string, cursor: number) => {
    setBody(value);
    setDirty(true);
    // Open the picker when the caret sits inside an unclosed "[[".
    const before = value.slice(0, cursor);
    const open = before.lastIndexOf('[[');
    if (open === -1 || before.slice(open).includes(']]')) {
      setAutocomplete(null);
      return;
    }
    setAutocomplete({ query: before.slice(open + 2), start: open });
    setActiveSuggestion(0);
  };

  const applySuggestion = useCallback(
    (s: Suggestion) => {
      if (!autocomplete) return;
      const el = textareaRef.current;
      const cursor = el?.selectionStart ?? body.length;
      const insert = `[[${s.slug}|${s.title}]]`;
      setBody(body.slice(0, autocomplete.start) + insert + body.slice(cursor));
      setAutocomplete(null);
      setDirty(true);
      requestAnimationFrame(() => {
        const pos = autocomplete.start + insert.length;
        el?.focus();
        el?.setSelectionRange(pos, pos);
      });
    },
    [autocomplete, body],
  );

  const save = async () => {
    if (!title.trim()) {
      setError('Give the note a title first');
      return;
    }
    setSaving(true);
    setError(null);
    const tagList = tags
      .split(',')
      .map((t) => t.trim().replace(/^#/, ''))
      .filter(Boolean);
    try {
      if (isNew) {
        const created = await createDoc({ title: title.trim(), body, type, tags: tagList });
        setDirty(false);
        navigate(docPath(created.slug));
      } else {
        await updateDoc(slug, { title: title.trim(), body, tags: tagList, type });
        setDirty(false);
        navigate(docPath(slug));
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault();
      void save();
      return;
    }
    if (!autocomplete || suggestions.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveSuggestion((i) => (i + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveSuggestion((i) => (i - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      applySuggestion(suggestions[activeSuggestion]);
    } else if (e.key === 'Escape') {
      setAutocomplete(null);
    }
  };

  if (!isNew && existing.loading) return <div className="container muted">Loading…</div>;
  if (!isNew && existing.error) {
    return (
      <div className="container">
        <div className="empty-state">
          <h2>Cannot edit this</h2>
          <p className="error">{existing.error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container editor">
      <div className="editor-toolbar">
        <input
          className="title-input"
          value={title}
          placeholder="Note title"
          aria-label="Note title"
          onChange={(e) => {
            setTitle(e.target.value);
            setDirty(true);
          }}
        />
        <select
          value={type}
          aria-label="Note type"
          onChange={(e) => {
            setType(e.target.value);
            setDirty(true);
          }}
        >
          {NOTE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          className="tags-input"
          value={tags}
          placeholder="tags, comma separated"
          aria-label="Tags"
          onChange={(e) => {
            setTags(e.target.value);
            setDirty(true);
          }}
        />
        <button onClick={save} disabled={saving}>
          {saving ? 'Saving…' : isNew ? 'Create' : 'Save'}
        </button>
        {!isNew && (
          <button
            className="ghost danger"
            disabled={saving}
            onClick={async () => {
              if (!window.confirm(`Delete “${title}” permanently?`)) return;
              await deleteDoc(slug);
              setDirty(false);
              navigate('/browse');
            }}
          >
            Delete
          </button>
        )}
        <button
          className="ghost"
          onClick={() => {
            if (dirty && !window.confirm('Discard unsaved changes?')) return;
            navigate(isNew ? '/browse' : docPath(slug));
          }}
        >
          Cancel
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      <p className="muted small">
        Type <code>[[</code> to link another note. ⌘S / Ctrl+S saves.
      </p>

      <div className="editor-panes">
        <div className="editor-pane">
          <textarea
            ref={textareaRef}
            value={body}
            spellCheck
            aria-label="Note body"
            placeholder={'# Your note\n\nOne idea per note. Link generously with [[.'}
            onChange={(e) => onBodyChange(e.target.value, e.target.selectionStart)}
            onKeyDown={onKeyDown}
          />
          {autocomplete && suggestions.length > 0 && (
            <div className="autocomplete">
              {suggestions.map((s, i) => (
                <button
                  key={s.slug}
                  className={`dropdown-item${i === activeSuggestion ? ' active' : ''}`}
                  onMouseEnter={() => setActiveSuggestion(i)}
                  onClick={() => applySuggestion(s)}
                >
                  {s.title}
                  <span className="muted small"> {s.slug}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="editor-pane preview">
          <Markdown content={body} links={links} />
        </div>
      </div>
    </div>
  );
}

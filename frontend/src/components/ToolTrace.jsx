import { useState } from 'react';

/**
 * ToolTrace — shows which tools ran during a response.
 *
 * Each tool step renders as a collapsed grey pill. Clicking it expands
 * a detail panel. WebResearch results render as individual source cards
 * with title, URL, and a snippet. CollisionCheck renders its text result.
 */
function ToolTrace({ steps }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div style={styles.wrapper}>
      {steps.map((step, idx) => (
        <ToolStep key={idx} step={step} />
      ))}
    </div>
  );
}

function ToolStep({ step }) {
  const [open, setOpen] = useState(false);

  const isRunning = !step.result;
  const icon = TOOL_ICONS[step.tool] ?? '⚙️';

  // Parse result — may be plain text or JSON (web_research sources)
  let parsedResult = null;
  let sources = null;
  if (step.result) {
    try {
      const obj = JSON.parse(step.result);
      if (obj && obj.type === 'web_research' && Array.isArray(obj.sources)) {
        sources = obj.sources;
      } else {
        parsedResult = step.result;
      }
    } catch {
      parsedResult = step.result;
    }
  }

  return (
    <div style={styles.stepWrapper}>
      {/* Collapsed pill / header row */}
      <button
        type="button"
        style={{
          ...styles.pill,
          ...(open ? styles.pillOpen : {}),
          cursor: isRunning ? 'default' : 'pointer',
        }}
        onClick={() => !isRunning && setOpen(o => !o)}
        disabled={isRunning}
        aria-expanded={open}
      >
        {/* Status dot */}
        <span
          style={{
            ...styles.dot,
            background: isRunning
              ? 'rgba(255,255,255,0.3)'
              : TOOL_COLORS[step.tool] ?? '#6b7280',
            animation: isRunning ? 'pulse 1.2s ease-in-out infinite' : 'none',
          }}
        />

        {/* Icon + name */}
        <span style={styles.pillIcon}>{icon}</span>
        <span style={styles.pillName}>{TOOL_LABELS[step.tool] ?? step.tool}</span>

        {/* Status badge */}
        {isRunning ? (
          <span style={styles.badgeRunning}>running…</span>
        ) : (
          <span style={styles.badgeDone}>
            {sources ? `${sources.length} source${sources.length !== 1 ? 's' : ''}` : 'done'}
          </span>
        )}

        {/* Expand chevron */}
        {!isRunning && (
          <span style={{ ...styles.chevron, transform: open ? 'rotate(180deg)' : 'none' }}>
            ▾
          </span>
        )}
      </button>

      {/* Expanded detail panel */}
      {open && (
        <div style={styles.panel}>
          {/* Web research: source cards */}
          {sources && sources.length > 0 && (
            <div style={styles.sourceList}>
              {sources.map((src, i) => (
                <SourceCard key={i} source={src} index={i} />
              ))}
            </div>
          )}

          {/* Plain text result (collision check, errors, etc.) */}
          {parsedResult && (
            <p style={styles.plainResult}>{parsedResult}</p>
          )}
        </div>
      )}
    </div>
  );
}

function SourceCard({ source, index }) {
  const [expanded, setExpanded] = useState(false);
  const domain = source.url ? (() => {
    try { return new URL(source.url).hostname.replace('www.', ''); }
    catch { return source.url; }
  })() : null;

  return (
    <div style={styles.sourceCard}>
      {/* Card header */}
      <div style={styles.sourceHeader}>
        <span style={styles.sourceIndex}>{index + 1}</span>
        <div style={styles.sourceMeta}>
          {domain && <span style={styles.sourceDomain}>{domain}</span>}
          <span style={styles.sourceTitle}>
            {source.url ? (
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                style={styles.sourceLink}
                onClick={e => e.stopPropagation()}
              >
                {source.title || source.url}
              </a>
            ) : (
              source.title || 'Untitled'
            )}
          </span>
        </div>

        {source.snippet && (
          <button
            type="button"
            style={styles.expandBtn}
            onClick={() => setExpanded(e => !e)}
            aria-label={expanded ? 'Collapse snippet' : 'Expand snippet'}
          >
            {expanded ? '−' : '+'}
          </button>
        )}
      </div>

      {/* Expandable snippet */}
      {expanded && source.snippet && (
        <p style={styles.sourceSnippet}>{source.snippet}</p>
      )}
    </div>
  );
}

/* ── Tool metadata ───────────────────────────────────────────── */
const TOOL_ICONS = {
  CollisionCheck: '🔍',
  WebResearch: '🌐',
  AcademicSearch: '🔬',
  GithubSearch: '💻',
  GenerateChart: '📊',
  HackerNewsSearch: '▲',
  WikipediaSummary: '📖',
  RedditSearch: '💬',
  NpmSearch: '📦',
  CrossrefSearch: '📚',
  WorldBankIndicator: '📈',
  Coinpaprika: '🪙',
  FetchNewsletterFeeds: '📰',
};

const TOOL_LABELS = {
  CollisionCheck: 'Novelty Check',
  WebResearch: 'Web Search',
  AcademicSearch: 'arXiv Search',
  GithubSearch: 'GitHub Search',
  GenerateChart: 'Chart Generator',
  HackerNewsSearch: 'Hacker News',
  WikipediaSummary: 'Wikipedia Summary',
  RedditSearch: 'Reddit Search',
  NpmSearch: 'npm Registry Search',
  CrossrefSearch: 'CrossRef Literature',
  WorldBankIndicator: 'World Bank Indicators',
  Coinpaprika: 'Coinpaprika Crypto',
  FetchNewsletterFeeds: 'Trends / Newsletter feeds',
};

const TOOL_COLORS = {
  CollisionCheck: '#f59e0b',
  WebResearch: '#38bdf8',
  AcademicSearch: '#a78bfa',
  GithubSearch: '#e2e8f0',
  GenerateChart: '#10b981',
  HackerNewsSearch: '#ff6600',
  WikipediaSummary: '#e2e8f0',
  RedditSearch: '#ff4500',
  NpmSearch: '#cb3837',
  CrossrefSearch: '#f43f5e',
  WorldBankIndicator: '#3b82f6',
  Coinpaprika: '#fbbf24',
  FetchNewsletterFeeds: '#8b5cf6',
};

/* ── Styles ──────────────────────────────────────────────────── */
const styles = {
  wrapper: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    marginTop: '12px',
  },

  /* Pill row */
  stepWrapper: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0',
  },
  pill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '7px',
    width: '100%',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '8px',
    padding: '6px 10px',
    color: '#6b7280',
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    textAlign: 'left',
    transition: 'background 0.15s, border-color 0.15s',
  },
  pillOpen: {
    background: 'rgba(255,255,255,0.05)',
    borderColor: 'rgba(255,255,255,0.14)',
    borderBottomLeftRadius: 0,
    borderBottomRightRadius: 0,
  },
  dot: {
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    flexShrink: 0,
  },
  pillIcon: {
    fontSize: '12px',
  },
  pillName: {
    flex: 1,
    color: '#9ca3af',
    letterSpacing: '0.03em',
  },
  badgeRunning: {
    fontSize: '10px',
    color: '#6b7280',
    fontStyle: 'italic',
  },
  badgeDone: {
    fontSize: '10px',
    color: '#4b5563',
    background: 'rgba(255,255,255,0.05)',
    padding: '1px 6px',
    borderRadius: '999px',
  },
  chevron: {
    fontSize: '11px',
    color: '#4b5563',
    transition: 'transform 0.2s ease',
    display: 'inline-block',
    flexShrink: 0,
  },

  /* Expanded panel */
  panel: {
    background: 'rgba(0,0,0,0.25)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderTop: 'none',
    borderBottomLeftRadius: '8px',
    borderBottomRightRadius: '8px',
    padding: '10px 12px',
  },

  plainResult: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: '#6b7280',
    lineHeight: '1.6',
    margin: 0,
  },

  /* Source list */
  sourceList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },

  sourceCard: {
    background: 'rgba(255,255,255,0.02)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '6px',
    overflow: 'hidden',
  },
  sourceHeader: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '8px',
    padding: '7px 10px',
  },
  sourceIndex: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: '#38bdf8',
    minWidth: '14px',
    paddingTop: '1px',
    flexShrink: 0,
  },
  sourceMeta: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
    minWidth: 0,
  },
  sourceDomain: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    color: '#4b5563',
    letterSpacing: '0.05em',
    textTransform: 'lowercase',
  },
  sourceTitle: {
    fontSize: '11px',
    color: '#9ca3af',
    lineHeight: '1.4',
    wordBreak: 'break-word',
  },
  sourceLink: {
    color: '#60a5fa',
    textDecoration: 'none',
    transition: 'color 0.15s',
  },
  expandBtn: {
    background: 'none',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '4px',
    color: '#4b5563',
    cursor: 'pointer',
    fontSize: '13px',
    lineHeight: 1,
    padding: '2px 5px',
    flexShrink: 0,
    alignSelf: 'center',
  },
  sourceSnippet: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: '#4b5563',
    lineHeight: '1.6',
    margin: '0',
    padding: '6px 10px 8px',
    borderTop: '1px solid rgba(255,255,255,0.04)',
  },
};

export default ToolTrace;

import { useState, useCallback, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import mermaid from 'mermaid';
import 'highlight.js/styles/github-dark.css';
import 'katex/dist/katex.min.css';

// Initialize mermaid configurations
try {
  mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    securityLevel: 'loose',
    fontFamily: 'monospace',
    themeVariables: {
      background: '#18181b', // matching Tailwind's zinc-900 / user's dark theme
      primaryColor: '#27272a', // zinc-800
      primaryTextColor: '#f4f4f5',
      lineColor: '#52525b', // zinc-600
      arrowheadColor: '#a1a1aa'
    }
  });
} catch (e) {
  console.error('Failed to initialize mermaid:', e);
}

let mermaidIdCounter = 0;

// Remove emoji, variation selectors, ZWJ and other pictographic glyphs that
// mermaid 11.x chokes on (e.g. "4️⃣ System Flowchart").
function stripEmojis(str) {
  return str
    .replace(
      /[\u{1F300}-\u{1FAFF}\u{1F900}-\u{1F9FF}\u{2600}-\u{27BF}\u{2300}-\u{23FF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\u{1F1E6}-\u{1F1FF}\u{200D}]/gu,
      ''
    )
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

// A label is safe unquoted only if it is plain ASCII-ish words/numbers/punct.
function labelNeedsQuote(s) {
  const t = s.trim();
  if (t.length === 0) return false;
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    return false;
  }
  return /[^A-Za-z0-9 _.,:;'"-]/.test(t);
}

function quoteLabel(s) {
  const t = s.trim().replace(/"/g, "'");
  return `"${t}"`;
}

// Self-heal the chart text: strip emoji, fix hallucinated arrows, and quote any
// node/edge labels that contain characters mermaid can't parse unquoted.
function sanitizeMermaid(chart) {
  let c = chart.trim();
  // Drop a stray leading language/header line.
  c = c.replace(/^(mermaid|flowchart)\s*\n/i, '');
  c = stripEmojis(c);
  // Fix the model's right-facing labeled-arrow mistake: -->|text|> -> -->|text|
  c = c.replace(/\|([^|\n]+?)\|>/g, '|$1|');

  const out = c.split('\n').map((line) => {
    let l = line;
    // Edge labels: A-->|label|B  or  A---|label|B
    l = l.replace(/(-->|---)\|([^|\n]+?)\|/g, (m, arrow, label) =>
      labelNeedsQuote(label) ? `${arrow}${quoteLabel(label)}` : m
    );
    // Node shapes, most-nested first.
    l = l.replace(/([A-Za-z0-9_]+)(\(\()([^()]*)(\)\))/g, (m, id, open, text) =>
      labelNeedsQuote(text) ? `${id}((${quoteLabel(text)}))` : m
    );
    l = l.replace(/([A-Za-z0-9_]+)(\[)([^[\]]*)\]/g, (m, id, open, text) =>
      labelNeedsQuote(text) ? `${id}[${quoteLabel(text)}]` : m
    );
    l = l.replace(/([A-Za-z0-9_]+)(\{)([^{}]*)\}/g, (m, id, open, text) =>
      labelNeedsQuote(text) ? `${id}{${quoteLabel(text)}}` : m
    );
    l = l.replace(/([A-Za-z0-9_]+)(\()([^()]*)(\))/g, (m, id, open, text) =>
      labelNeedsQuote(text) ? `${id}(${quoteLabel(text)})` : m
    );
    return l;
  });

  return out.join('\n');
}

// Last-resort rescue for the model's ASCII-art "flowcharts": lines like
//   Start
//   |--[Power-On]--> Init ESP32
//   |   +---[DeepWork]---|
//   |   |   Reset Counter |
// Convert them into valid `graph TD` mermaid. Best-effort but always parseable.
function asciiFlowToMermaid(text) {
  const lines = text.split('\n');

  const normalizeSpace = (s) =>
    s
      .replace(/[    ]/g, ' ') // nbsp / narrow nbsp / thin space
      .replace(/[\u2011‑]/g, '-') // non-breaking hyphens
      .replace(/[\u200B-\u200D﻿]/g, '')
      .trim();

  const nodes = new Map(); // label -> id
  const nodeLabel = new Map(); // id -> label
  const edges = []; // { from, to, label }
  const stack = []; // { indent, id, isBox }
  let rootId = null;
  let counter = 0;

  const addNode = (rawLabel) => {
    const label = normalizeSpace(rawLabel);
    if (!label) return null;
    if (nodes.has(label)) return nodes.get(label);
    const id = `n${++counter}`;
    nodes.set(label, id);
    nodeLabel.set(id, label);
    return id;
  };

  for (const rawLine of lines) {
    // Measure indentation by treating `|` connectors as spaces.
    const indentLine = rawLine.replace(/\|/g, ' ');
    const indent = indentLine.length - indentLine.trimStart().length;
    const content = rawLine.replace(/^\s*\|*/, '').trim();

    // Skip pure decoration lines (only | - + and spaces).
    if (/^[|\-+ ]*$/.test(content)) continue;

    // Pop back up to the correct nesting level.
    while (stack.length && stack[stack.length - 1].indent >= indent) {
      stack.pop();
    }
    const parent = stack.length ? stack[stack.length - 1].id : rootId;

    // Box open:  +---[Name]---+  or  +---[Name]---|
    const boxMatch = content.match(/^\+[-]*\[([^\]]+)\]/);
    if (boxMatch) {
      const id = addNode(boxMatch[1]);
      if (id && parent) edges.push({ from: parent, to: id, label: '' });
      if (id) stack.push({ indent, id, isBox: true });
      continue;
    }

    const arrowIdx = content.indexOf('-->');
    if (arrowIdx !== -1) {
      const before = content.slice(0, arrowIdx);
      const target = normalizeSpace(content.slice(arrowIdx + 3));
      const bm = before.match(/\[([^\]]*)\]\s*$/);
      const label = bm ? normalizeSpace(bm[1]) : '';
      const id = addNode(target);
      if (id && parent) edges.push({ from: parent, to: id, label });
      // Push the target so deeper sub-branches nest under it; same-indent
      // siblings pop it again, so they still hang from the shared parent.
      if (id) stack.push({ indent, id, isBox: false });
      continue;
    }

    // First real line with no arrow and no box = the root node.
    if (!rootId) {
      rootId = addNode(content);
      if (rootId) stack.push({ indent: -1, id: rootId, isBox: false });
      continue;
    }

    // Otherwise it's body text inside the current (box) node — append it.
    if (parent && nodeLabel.has(parent)) {
      nodeLabel.set(parent, `${nodeLabel.get(parent)}<br/>${normalizeSpace(content)}`);
    }
  }

  if (!nodes.size) return `graph TD\n  A["Flow"]`;

  let out = 'graph TD\n';
  for (const [label, id] of nodes.entries()) {
    out += `  ${id}["${label.replace(/"/g, "'")}"]\n`;
  }
  for (const e of edges) {
    if (!e.from || !e.to) continue;
    const lbl = e.label ? `|${e.label.replace(/"/g, "'")}|` : '';
    out += `  ${e.from} -->${lbl} ${e.to}\n`;
  }
  return out;
}

function MermaidDiagram({ chart }) {
  const mountRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!mountRef.current) return;

    // Build candidate charts: the sanitized original first, then an ASCII-art
    // rescue. Use the first one mermaid can actually parse.
    const candidates = [sanitizeMermaid(chart)];
    let cleanedChart = candidates[0];
    try {
      // mermaid.parse throws on invalid syntax; treat a failure as a signal to
      // try the ASCII rescue rather than rendering garbage.
      mermaid.parse(cleanedChart);
    } catch (parseErr) {
      console.warn('Mermaid parse failed, attempting ASCII-flow rescue:', parseErr?.message);
      const rescued = asciiFlowToMermaid(chart);
      if (rescued && rescued !== cleanedChart) {
        candidates.push(rescued);
        cleanedChart = rescued;
      }
    }

    // Auto-prepend a graph declaration if the model omitted one.
    const hasHeader = /^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|journey|mindmap|timeline|quadrant|sankey|kanban|requirement|architecture|db)\b/i.test(
      cleanedChart
    );
    if (!hasHeader) {
      cleanedChart = `graph TD\n${cleanedChart}`;
    }

    const id = `mermaid-${Date.now()}-${mermaidIdCounter++}`;
    mountRef.current.innerHTML = ''; // Clear previous content

    const element = document.createElement('div');
    element.className = 'mermaid';
    element.id = id;
    element.textContent = cleanedChart;
    mountRef.current.appendChild(element);

    setError(null);

    let cancelled = false;

    // Call mermaid.run inside a timeout to let the DOM settle, and await it so
    // async parse/render rejections are caught instead of surfacing raw errors.
    const timer = setTimeout(async () => {
      try {
        try {
          await mermaid.parse(cleanedChart);
        } catch (parseErr) {
          console.warn('Mermaid parse warning (still attempting render):', parseErr);
        }

        await mermaid.run({ nodes: [element] });

        if (cancelled) return;

        // Mobile-readability fix: set SVG to its natural viewBox width to prevent scaling down
        const svg = element.querySelector('svg');
        if (svg) {
          const viewBox = svg.getAttribute('viewBox');
          if (viewBox) {
            const parts = viewBox.split(' ');
            if (parts.length === 4) {
              const width = parseFloat(parts[2]);
              if (width && width > 0) {
                svg.style.width = `${width}px`;
                svg.style.maxWidth = 'none';
                svg.style.height = 'auto';
              }
            }
          }
        }
      } catch (err) {
        console.error('Mermaid render error:', err);
        if (!cancelled) setError(err?.message || 'Flowchart rendering failed');
      }
    }, 50);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [chart]);

  const handleClick = () => {
    // Send custom message to the chat
    const event = new CustomEvent('ideator_send_message', {
      detail: {
        prompt: `Explain this flowchart:\n\n\`\`\`flowchart\n${chart}\n\`\`\``
      }
    });
    window.dispatchEvent(event);
  };

  if (error) {
    return (
      <div style={{
        margin: '16px 0',
        padding: '12px 16px',
        background: 'rgba(239, 68, 68, 0.05)',
        border: '1px solid rgba(239, 68, 68, 0.15)',
        borderRadius: '8px',
        color: '#f87171',
        fontSize: '13px',
        fontFamily: 'monospace',
        whiteSpace: 'pre-wrap',
        overflowX: 'auto'
      }}>
        <div><strong>Flowchart Render Error:</strong></div>
        <div style={{ marginTop: '4px' }}>{error}</div>
        <details style={{ marginTop: '8px', cursor: 'pointer' }}>
          <summary style={{ color: '#9ca3af', fontSize: '12px' }}>Show raw source code</summary>
          <pre style={{ marginTop: '8px', padding: '8px', background: '#18181b', borderRadius: '4px', color: '#e5e7eb' }}>{chart}</pre>
        </details>
      </div>
    );
  }

  return (
    <div 
      onClick={handleClick}
      className="mermaid-wrapper"
      style={{ 
        background: '#18181b', 
        border: '1px solid #27272a', 
        borderRadius: '8px', 
        padding: '24px 16px 12px 16px', 
        margin: '16px 0', 
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        cursor: 'pointer',
        transition: 'border-color 0.2s ease, background-color 0.2s ease',
        position: 'relative',
        width: '100%',
        boxSizing: 'border-box'
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = '#3f3f46';
        e.currentTarget.style.backgroundColor = '#202023';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = '#27272a';
        e.currentTarget.style.backgroundColor = '#18181b';
      }}
    >
      <div 
        ref={mountRef} 
        style={{ 
          width: '100%', 
          overflowX: 'auto',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center'
        }}
      />
      <div style={{
        marginTop: '12px',
        fontSize: '11px',
        color: '#71717a',
        fontFamily: 'var(--font-sans)',
        borderTop: '1px solid #27272a',
        paddingTop: '8px',
        width: '100%',
        textAlign: 'center',
        pointerEvents: 'none',
        userSelect: 'none'
      }}>
        Click flowchart to explain it
      </div>
    </div>
  );
}

const preprocessMath = (text) => {
  if (!text) return '';
  let processed = text;
  
  // 0. Replace raw or HTML-encoded <br> and <br /> tags with standard markdown line breaks (two spaces and a newline)
  processed = processed.replace(/<br\s*\/?>|&lt;br\s*\/?&gt;/gi, '  \n');
  
  // 1. Replace \( and \) with $ (if they are escaped backslash delimiters)
  processed = processed.replace(/\\\(|\\\)/g, '$');
  
  // 2. Replace \[ and \] with $$
  processed = processed.replace(/\\\[|\\\]/g, '$$$$');
  
  // 3. Convert normal parentheses containing LaTeX commands to inline $...$
  processed = processed.replace(/\(([^)\n]+?)\)/g, (match, p1) => {
    const hasMathSymbol = /[\\]|_[a-zA-Z0-9]|\^|[\u03B1-\u03C9]/.test(p1) || 
                          p1.includes('\\') || 
                          p1.includes('^') ||
                          p1.includes('_') ||
                          /^[a-zA-Z]\s*=\s*/.test(p1);
    if (hasMathSymbol) {
      return `$${p1}$`;
    }
    return match;
  });

  // 4. Convert normal brackets containing LaTeX commands to block $$...$$
  processed = processed.replace(/\[([^\]\n]+?)\]/g, (match, p1) => {
    const hasMathSymbol = /[\\]|_[a-zA-Z0-9]|\^|[\u03B1-\u03C9]/.test(p1) || 
                          p1.includes('\\') || 
                          p1.includes('^') ||
                          p1.includes('_') ||
                          /^[a-zA-Z]\s*=\s*/.test(p1);
    if (hasMathSymbol) {
      return `\n$$\n${p1}\n$$\n`;
    }
    return match;
  });
  
  return processed;
};

/**
 * MarkdownRenderer — renders AI model output with rich colorful styling.
 * The overall website is black/white, but AI responses are intentionally vibrant.
 * Includes copy-to-clipboard on code blocks and KaTeX math rendering.
 */
function CodeBlock({ className, children, ...props }) {
  const [copied, setCopied] = useState(false);
  const code = String(children).replace(/\n$/, '');

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [code]);

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={handleCopy}
        title="Copy code"
        style={{
          position: 'absolute',
          top: '8px',
          right: '8px',
          background: copied ? 'rgba(99, 255, 150, 0.15)' : 'rgba(255,255,255,0.08)',
          border: `1px solid ${copied ? 'rgba(99, 255, 150, 0.4)' : 'rgba(255,255,255,0.15)'}`,
          borderRadius: '6px',
          color: copied ? '#6bffaa' : '#aaa',
          cursor: 'pointer',
          fontSize: '11px',
          fontFamily: 'var(--font-mono)',
          padding: '3px 8px',
          transition: 'all 0.2s ease',
          zIndex: 2,
          lineHeight: '1.4',
        }}
      >
        {copied ? '✓ Copied' : 'Copy'}
      </button>
      <code className={className} {...props}>{children}</code>
    </div>
  );
}

function MarkdownRenderer({ content }) {
  const processedContent = preprocessMath(content);
  return (
    <div className="ai-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
        components={{
          // Headings with colorful gradient accents
          h1: ({ children }) => (
            <h1 className="ai-md-h1">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="ai-md-h2">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="ai-md-h3">{children}</h3>
          ),
          // Paragraphs — soft off-white for readability
          p: ({ children }) => (
            <p className="ai-md-p">{children}</p>
          ),
          // Bold — warm amber
          strong: ({ children }) => (
            <strong className="ai-md-strong">{children}</strong>
          ),
          // Italic — lavender
          em: ({ children }) => (
            <em className="ai-md-em">{children}</em>
          ),
          // Inline code — teal monospace
          code: ({ className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '');
            const lang = match ? match[1].toLowerCase() : '';
            
            if (lang === 'mermaid' || lang === 'flowchart') {
              return <MermaidDiagram chart={String(children).replace(/\n$/, '')} />;
            }
            
            const isInline = !className && !String(children).includes('\n');
            if (isInline) {
              return <code className="ai-md-inline-code" {...props}>{children}</code>;
            }
            
            return <CodeBlock className={className} {...props}>{children}</CodeBlock>;
          },
          // Code block wrapper
          pre: ({ children }) => (
            <pre className="ai-md-pre">{children}</pre>
          ),
          // Unordered lists — colorful bullet markers
          ul: ({ children }) => (
            <ul className="ai-md-ul">{children}</ul>
          ),
          // Ordered lists
          ol: ({ children }) => (
            <ol className="ai-md-ol">{children}</ol>
          ),
          // List items
          li: ({ children }) => (
            <li className="ai-md-li">{children}</li>
          ),
          // Blockquotes — rose/salmon accent
          blockquote: ({ children }) => (
            <blockquote className="ai-md-blockquote">{children}</blockquote>
          ),
          // Horizontal rule
          hr: () => <hr className="ai-md-hr" />,
          // Links — cyan with underline
          a: ({ href, children }) => (
            <a
              className="ai-md-link"
              href={href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          ),
          // Tables
          table: ({ children }) => (
            <div className="ai-md-table-wrapper">
              <table className="ai-md-table">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="ai-md-th">{children}</th>
          ),
          td: ({ children }) => (
            <td className="ai-md-td">{children}</td>
          ),
          // Images - responsive and constrained to fit smaller/mobile layouts
          img: ({ src, alt }) => (
            <img
              src={src}
              alt={alt}
              style={{
                maxWidth: '100%',
                height: 'auto',
                borderRadius: '8px',
                margin: '12px 0',
                display: 'block',
                boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
              }}
            />
          ),
        }}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownRenderer;

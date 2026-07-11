import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';

/**
 * MarkdownRenderer — renders AI model output with rich colorful styling.
 * The overall website is black/white, but AI responses are intentionally vibrant.
 */
function MarkdownRenderer({ content }) {
  return (
    <div className="ai-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
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
          code: ({ inline, className, children, ...props }) => {
            if (inline) {
              return <code className="ai-md-inline-code" {...props}>{children}</code>;
            }
            // Block code handled by rehype-highlight via pre > code
            return <code className={className} {...props}>{children}</code>;
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
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownRenderer;

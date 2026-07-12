import { useState, useEffect, useRef, useCallback } from 'react';
import ToolTrace from './ToolTrace';
import MarkdownRenderer from './MarkdownRenderer';
import { apiFetch, getWebSocketUrl } from '../utils/api';

const SLASH_COMMANDS = [
  { prefix: '/scamper', desc: 'Mutate product using SCAMPER framework' },
  { prefix: '/jtbd', desc: 'Identify target user Jobs-to-be-Done tasks' },
  { prefix: '/first', desc: 'Deconstruct ideas using First Principles' },
  { prefix: '/score', desc: 'Evaluate idea across 5-dimension scorecard' },
];

function useWindowSize() {
  const [width, setWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1200);
  useEffect(() => {
    const handleResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  return width < 768;
}

// ─── Prompt library — 6 high-quality starters ─────────────────────────────
const STARTER_PROMPTS = [
  'Turn a daily frustration into a product idea',
  'Find me the latest research on transformer efficiency',
  'Suggest a developer tool that saves 10+ hours/week',
  'Give me a hackathon idea with a killer 60-second demo',
  'Design a hardware project using discrete components only',
  'What IoT + AI startup idea can I build on ESP32?',
];

const getDayPart = () => {
  const hour = new Date().getHours();
  if (hour < 12) return 'morning';
  if (hour < 18) return 'afternoon';
  return 'evening';
};

function ChatArea({ activeChatId, user, onCreateChat }) {
  const [messages, setMessages] = useState([]);
  const [inputPrompt, setInputPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [followupsByMsgId, setFollowupsByMsgId] = useState({});
  const [userScrolled, setUserScrolled] = useState(false);
  const [isDeepResearch, setIsDeepResearch] = useState(false);
  const [agentStep, setAgentStep] = useState(null);
  const [showSlashMenu, setShowSlashMenu] = useState(false);
  const chatEndRef = useRef(null);
  const messageListRef = useRef(null);
  const wsRef = useRef(null);
  const isMobile = useWindowSize();
  const [loadingHistory, setLoadingHistory] = useState(false);

  useEffect(() => {
    if (activeChatId) {
      fetchMessages();
      setFollowupsByMsgId({});
    } else {
      setMessages([]);
      setFollowupsByMsgId({});
    }
    setUserScrolled(false);
  }, [activeChatId]);

  // Listener to set input prompt dynamically (e.g. from MindMap node double clicks)
  useEffect(() => {
    const handleSetPrompt = (e) => {
      if (e.detail && e.detail.prompt) {
        setInputPrompt(e.detail.prompt);
      }
    };
    window.addEventListener('ideator_set_prompt', handleSetPrompt);
    return () => window.removeEventListener('ideator_set_prompt', handleSetPrompt);
  }, []);

  const handleSendRef = useRef(null);
  useEffect(() => {
    handleSendRef.current = handleSend;
  });

  // Listener to send a message dynamically (e.g., explaining a clicked flowchart)
  useEffect(() => {
    const handleSendMessage = (e) => {
      if (e.detail && e.detail.prompt && handleSendRef.current) {
        handleSendRef.current(null, e.detail.prompt);
      }
    };
    window.addEventListener('ideator_send_message', handleSendMessage);
    return () => window.removeEventListener('ideator_send_message', handleSendMessage);
  }, []);

  // Smart auto-scroll: only scroll if user hasn't manually scrolled up
  useEffect(() => {
    if (!userScrolled) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, streamingMessage, userScrolled]);

  const handleScroll = useCallback(() => {
    const el = messageListRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    setUserScrolled(!isAtBottom);
  }, []);

  const fetchMessages = async (chatId = activeChatId) => {
    if (!chatId) return;
    setLoadingHistory(true);
    try {
      const res = await apiFetch(`/api/chats/${chatId}/messages`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data);
      }
    } catch (err) {
      console.error('Failed to fetch messages:', err);
    } finally {
      setLoadingHistory(false);
    }
  };

  // Export chat as Markdown
  const handleExport = useCallback(() => {
    if (!messages.length) return;
    const md = messages
      .map(m => `**${m.sender === 'user' ? 'You' : 'Ideator'}:**\n\n${m.content}`)
      .join('\n\n---\n\n');
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ideator-chat-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [messages]);

  // Copy message content to clipboard
  const handleCopyMessage = useCallback((content) => {
    navigator.clipboard.writeText(content);
  }, []);

  const handleInputChange = (e) => {
    const val = e.target.value;
    setInputPrompt(val);
    if (val.startsWith('/') && !val.includes(' ')) {
      setShowSlashMenu(true);
    } else {
      setShowSlashMenu(false);
    }
  };

  const handleSelectSlashCommand = (prefix) => {
    setInputPrompt(prefix + ' ');
    setShowSlashMenu(false);
  };

  // Stop generation
  const handleStop = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setLoading(false);
    if (streamingMessage) {
      setMessages(prev => [...prev, { ...streamingMessage, id: String(Math.random()) }]);
      setStreamingMessage(null);
    }
  }, [streamingMessage]);

  const handleSend = async (e, overridePrompt) => {
    if (e) e.preventDefault();
    const prompt = (overridePrompt ?? inputPrompt).trim();
    if (!prompt || loading || !user) return;

    setInputPrompt('');
    setLoading(true);
    setErrorMsg(null);
    setUserScrolled(false);

    let chatId = activeChatId;
    if (!chatId) {
      setLoadingHistory(true);
      try {
        const response = await apiFetch('/api/chats', { method: 'POST' });
        if (!response.ok) throw new Error('Could not create a chat');
        const chat = await response.json();
        chatId = chat.id || chat._id;
        onCreateChat(chatId);
      } catch (err) {
        console.error('Failed to create chat:', err);
        setLoading(false);
        setLoadingHistory(false);
        setInputPrompt(prompt);
        return;
      }
    }

    // Instantly append user's message locally
    const userMsg = {
      id: String(Math.random()),
      sender: 'user',
      content: prompt,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMsg]);

    // Open WebSocket stream connection
    const sessionId = user.id || user._id;
    const wsUrl = getWebSocketUrl(`/api/chats/${chatId}/ws?session_id=${encodeURIComponent(sessionId)}`);

    let currentAssistantMsg = {
      id: String(Math.random()),
      sender: 'assistant',
      content: '',
      tool_steps: []
    };
    setStreamingMessage(currentAssistantMsg);

    const socket = new WebSocket(wsUrl);
    wsRef.current = socket;

    socket.onopen = () => {
      socket.send(JSON.stringify({ prompt, user_name: user.display_name, deep_research: isDeepResearch }));
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.event === 'narrative') {
        currentAssistantMsg = { ...currentAssistantMsg, content: currentAssistantMsg.content + data.text + '\n\n' };
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'tool_start') {
        currentAssistantMsg = {
          ...currentAssistantMsg,
          tool_steps: [...currentAssistantMsg.tool_steps, { tool: data.name, args: data.args, result: null }]
        };
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'tool_end') {
        currentAssistantMsg = {
          ...currentAssistantMsg,
          tool_steps: currentAssistantMsg.tool_steps.map(step =>
            step.tool === data.name && !step.result ? { ...step, result: data.result } : step
          )
        };
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'delta') {
        currentAssistantMsg = { ...currentAssistantMsg, content: currentAssistantMsg.content + data.text };
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'followups') {
        // Store follow-ups keyed by the message id
        const suggestions = data.suggestions || [];
        if (suggestions.length) {
          setFollowupsByMsgId(prev => ({ ...prev, [currentAssistantMsg.id]: suggestions }));
        }
      } else if (data.event === 'canvas_update') {
        const customEvent = new CustomEvent('ideator_canvas_ws_update', {
          detail: { chatId, canvas: data.canvas }
        });
        window.dispatchEvent(customEvent);
      } else if (data.event === 'agent_step') {
        setAgentStep(data.step);
      } else if (data.event === 'error') {
        setAgentStep(null);
        setErrorMsg(data.text || 'Something went wrong while generating a response.');
        currentAssistantMsg = { ...currentAssistantMsg, content: currentAssistantMsg.content + `\n\n⚠️ ${data.text}` };
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'done') {
        setAgentStep(null);
        socket.close();
        wsRef.current = null;
        const finalMsg = { ...currentAssistantMsg };
        setMessages(prev => [...prev, finalMsg]);
        setStreamingMessage(null);
        setLoading(false);
        fetchMessages(chatId);
      }
    };

    socket.onerror = () => {
      wsRef.current = null;
      setErrorMsg('Connection interrupted. Please check if the backend is running and try again.');
      setMessages(prev => [...prev, { ...currentAssistantMsg, id: String(Math.random()) }]);
      setStreamingMessage(null);
      setLoading(false);
    };

    socket.onclose = () => {
      wsRef.current = null;
      if (loading) {
        setMessages(prev => [...prev, { ...currentAssistantMsg, id: String(Math.random()) }]);
        setStreamingMessage(null);
        setLoading(false);
      }
    };
  };

  return (
    <div style={styles.chatContainer}>
      <style>{`
        @keyframes ideator-spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        @keyframes ideator-pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 1; }
        }
      `}</style>
      
      {errorMsg && (
        <div style={styles.errorBanner} role="alert">
          <span style={styles.errorText}>⚠️ {errorMsg}</span>
          <button type="button" style={styles.errorClose} onClick={() => setErrorMsg(null)} aria-label="Dismiss error">✕</button>
        </div>
      )}

      {loadingHistory ? (
        <div style={styles.loaderContainer}>
          <div style={styles.loaderSpinner} />
          <div style={styles.loaderText}>Retrieving ideation space...</div>
        </div>
      ) : !activeChatId ? (
        /* ─── HOME SCREEN ─── */
        <div style={styles.homeScreen} className="homeScreen">
          <div style={styles.eyebrow}>IDEATOR WORKSPACE</div>
          <h2 style={{ ...styles.homeTitle, fontSize: 'clamp(28px, 7vw, 48px)' }} className="fluid-home-title">
            Good {getDayPart()}, {user?.display_name?.split(' ')[0] || 'there'}.
          </h2>
          <p style={styles.homeSubtitle} className="fluid-home-subtitle">
            Start with a rough thought — a frustration, a project, a half-formed startup. We'll pressure-test it, sharpen it, and tell you what to build first.
          </p>

          <form style={styles.homeComposer} onSubmit={handleSend}>
            <textarea
              rows="3"
              placeholder="What are you curious about?"
              value={inputPrompt}
              onChange={(e) => setInputPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(e); }
              }}
              style={styles.homeInput}
              disabled={loading}
            />
              <div style={styles.composerFooter} className="composerFooter">
              <span style={styles.composerHint}>A new workspace opens when you send</span>
              <button type="submit" style={styles.homeSend} disabled={loading || !inputPrompt.trim()}>
                {loading ? 'Starting…' : 'Start exploring'}
              </button>
            </div>
          </form>

          {/* Starter prompt suggestion chips */}
          <div style={styles.categoryRow}>
            {STARTER_PROMPTS.map(p => (
              <button key={p} type="button" style={styles.suggestion} onClick={() => setInputPrompt(p)}>
                {p}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          {/* ─── CHAT HEADER ACTIONS ─── */}
          <div style={styles.chatHeader}>
            <div style={styles.chatHeaderRight}>
              {messages.length > 0 && (
                <button type="button" style={styles.headerBtn} className="headerBtn" onClick={handleExport} title="Export chat as Markdown">
                  ↓ Export
                </button>
              )}
            </div>
          </div>

          {/* ─── SCROLLABLE MESSAGE LIST ─── */}
          <div
            ref={messageListRef}
            onScroll={handleScroll}
            className="messageList"
            style={{ ...styles.messageList, padding: isMobile ? '16px' : '24px' }}
          >
            {messages.length === 0 && !streamingMessage && (
              <div style={{
                ...styles.introBox,
                margin: isMobile ? '20px auto' : '40px auto',
                padding: isMobile ? '16px' : '24px'
              }}>
                <h3 style={{ fontSize: isMobile ? '14px' : '16px' }}>Describe an idea and we'll help you find and sharpen it</h3>
                <p style={{ fontSize: isMobile ? '12px' : '14px' }}>
                  Example: "A peer-to-peer file locker that proves ownership with blockchain metadata"
                </p>
              </div>
            )}

            {messages.map((msg) => (
              <div key={msg.id} style={{ ...styles.messageWrapper, justifyContent: msg.sender === 'user' ? 'flex-end' : 'flex-start' }}>
                <div style={{
                  ...styles.messageBubble,
                  ...(msg.sender === 'user' ? styles.userBubble : styles.assistantBubble),
                  maxWidth: isMobile ? '95%' : '92%',
                  position: 'relative',
                }}>
                  {msg.sender === 'assistant' && (
                    <div style={styles.assistantLabel}>
                      <span style={styles.assistantLabelDot} />
                      <span style={styles.assistantLabelText}>Ideator</span>
                      {/* Copy message button */}
                      <button
                        type="button"
                        onClick={() => handleCopyMessage(msg.content)}
                        style={styles.copyMsgBtn}
                        title="Copy response"
                      >
                        ⎘
                      </button>
                    </div>
                  )}

                  {msg.sender === 'user' ? (
                    (() => {
                      const text = msg.content;
                      if (text.startsWith('/')) {
                        const match = text.match(/^(\/\w+)(.*)/s);
                        if (match) {
                          const [_, cmd, rest] = match;
                          return (
                            <div style={styles.messageContent}>
                              <span style={styles.userCmdPrefix}>{cmd}</span>{rest}
                            </div>
                          );
                        }
                      }
                      return <div style={styles.messageContent}>{text}</div>;
                    })()
                  ) : (
                    <MarkdownRenderer content={msg.content} />
                  )}

                  {/* Render inline trace logs */}
                  {msg.tool_steps && msg.tool_steps.length > 0 && (
                    <ToolTrace steps={msg.tool_steps} />
                  )}

                  {/* Follow-up suggestion chips */}
                  {msg.sender === 'assistant' && followupsByMsgId[msg.id]?.length > 0 && (
                    <div style={styles.followupRow}>
                      {followupsByMsgId[msg.id].map((q, i) => (
                        <button
                          key={i}
                          type="button"
                          style={styles.followupChip}
                          onClick={() => handleSend(null, q)}
                          disabled={loading}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Streaming message */}
            {streamingMessage && (
              <div style={{ ...styles.messageWrapper, justifyContent: 'flex-start' }}>
                <div style={{
                  ...styles.messageBubble,
                  ...styles.assistantBubble,
                  maxWidth: isMobile ? '95%' : '92%',
                }}>
                  <div style={styles.assistantLabel}>
                    <span style={{ ...styles.assistantLabelDot, animation: 'pulse 1.2s ease-in-out infinite' }} />
                    <span style={styles.assistantLabelText}>Ideator</span>
                  </div>
                  {agentStep && (
                    <div style={styles.agentStepCard}>
                      <span style={styles.agentStepIcon}>🔬</span>
                      <span style={styles.agentStepText}>{agentStep}</span>
                    </div>
                  )}
                  {streamingMessage.content ? (
                    <MarkdownRenderer content={streamingMessage.content} />
                  ) : (
                    !agentStep && (
                      <div style={styles.thinkingDots}>
                        <span className="thinking-dot" />
                        <span className="thinking-dot" />
                        <span className="thinking-dot" />
                      </div>
                    )
                  )}
                  {streamingMessage.tool_steps.length > 0 && (
                    <ToolTrace steps={streamingMessage.tool_steps} />
                  )}
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* ─── INPUT BAR ─── */}
          <form
            style={{ ...styles.inputForm, padding: isMobile ? '8px 12px calc(16px + env(safe-area-inset-bottom, 0px))' : '12px 24px calc(24px + env(safe-area-inset-bottom, 0px))' }}
            onSubmit={handleSend}
          >
            <div style={{ position: 'relative', width: '100%', maxWidth: '800px', margin: '0 auto' }}>
              {/* Slash Command Popover */}
              {showSlashMenu && (
                (() => {
                  const filtered = SLASH_COMMANDS.filter(cmd =>
                    cmd.prefix.toLowerCase().startsWith(inputPrompt.toLowerCase())
                  );
                  if (filtered.length === 0) return null;
                  return (
                    <div style={styles.slashPopover}>
                      <div style={styles.slashHeader}>CHOOSE AN IDEATION FRAMEWORK</div>
                      {filtered.map(cmd => (
                        <button
                          key={cmd.prefix}
                          type="button"
                          onClick={() => handleSelectSlashCommand(cmd.prefix)}
                          style={styles.slashItem}
                        >
                          <span style={styles.slashCmdText}>{cmd.prefix}</span>
                          <span style={styles.slashCmdDesc}>{cmd.desc}</span>
                        </button>
                      ))}
                    </div>
                  );
                })()
              )}

              <div style={styles.inputWrapper} className="inputWrapper">
                {/* Deep Research Toggle Button */}
                <button
                  type="button"
                  onClick={() => setIsDeepResearch(!isDeepResearch)}
                  style={{
                    ...styles.iconBtn,
                    color: isDeepResearch ? '#a78bfa' : 'var(--text-muted)',
                    background: isDeepResearch ? 'rgba(167, 139, 250, 0.12)' : 'transparent',
                    border: isDeepResearch ? '1px solid rgba(167, 139, 250, 0.3)' : 'none',
                    marginRight: '4px',
                  }}
                  title="Deep Research Mode (Pro Search)"
                  disabled={loading}
                >
                  🔬 {!isMobile && <span style={{ fontSize: '11px', fontWeight: 'bold', marginLeft: '4px', verticalAlign: 'middle' }}>DEEP</span>}
                </button>

                <input
                  type="text"
                  placeholder={loading ? 'Generating ideas…' : 'Type your concept/idea here, or / for commands…'}
                  value={inputPrompt}
                  onChange={handleInputChange}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') { e.preventDefault(); handleSend(e); }
                  }}
                  style={{ ...styles.inputField, fontSize: '16px' }}
                  disabled={loading}
                />

                {/* Stop button when streaming */}
                {loading && (
                  <button
                    type="button"
                    onClick={handleStop}
                    style={styles.stopBtn}
                    title="Stop generation"
                  >
                    ⏹
                  </button>
                )}

                {/* Send button */}
                {!loading && (
                  <button
                    type="submit"
                    style={{
                      ...styles.sendBtn,
                      backgroundColor: !inputPrompt.trim() ? 'var(--border-color)' : '#ffffff',
                      color: !inputPrompt.trim() ? 'var(--text-muted)' : '#000000',
                    }}
                    disabled={!inputPrompt.trim()}
                  >
                    →
                  </button>
                )}
              </div>
            </div>
          </form>
        </>
      )}
    </div>
  );
}

const styles = {
  chatContainer: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    flex: 1,
    overflow: 'hidden',
  },
  homeScreen: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    padding: '32px 20px',
    overflowY: 'auto',
    textAlign: 'center',
  },
  eyebrow: {
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '0.16em',
    marginBottom: '18px',
  },
  homeTitle: {
    color: 'var(--text-primary)',
    fontFamily: 'Georgia, serif',
    fontWeight: '400',
    letterSpacing: '-0.035em',
    lineHeight: '1.08',
    margin: 0,
  },
  homeSubtitle: {
    color: 'var(--text-secondary)',
    fontSize: '15px',
    lineHeight: '1.6',
    margin: '16px 0 28px',
    maxWidth: '490px',
  },
  homeComposer: {
    width: 'min(100%, 640px)',
    backgroundColor: 'var(--bg-secondary)',
    border: '1px solid #353535',
    borderRadius: '18px',
    boxShadow: '0 18px 55px rgba(0, 0, 0, 0.28)',
    overflow: 'hidden',
    textAlign: 'left',
  },
  homeInput: {
    background: 'transparent',
    border: 'none',
    boxSizing: 'border-box',
    color: 'var(--text-primary)',
    fontFamily: 'var(--font-sans)',
    fontSize: '16px',
    lineHeight: '1.5',
    minHeight: '112px',
    outline: 'none',
    padding: '20px 20px 10px',
    resize: 'vertical',
    width: '100%',
  },
  composerFooter: {
    alignItems: 'center',
    borderTop: '1px solid var(--border-color)',
    display: 'flex',
    justifyContent: 'space-between',
    padding: '12px 12px 12px 18px',
  },
  composerHint: {
    color: 'var(--text-muted)',
    fontSize: '11px',
  },
  homeSend: {
    backgroundColor: '#f2f2ef',
    border: 'none',
    borderRadius: '9px',
    color: '#151515',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: '700',
    padding: '10px 14px',
  },
  categoryRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '12px',
    justifyContent: 'center',
    marginTop: '20px',
    maxWidth: '720px',
  },
  categoryGroup: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '4px',
  },
  categoryLabel: {
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '0.1em',
    textTransform: 'uppercase',
  },
  categoryChips: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px',
    justifyContent: 'center',
  },
  suggestion: {
    background: 'transparent',
    border: '1px solid var(--border-color)',
    borderRadius: '999px',
    color: 'var(--text-secondary)',
    cursor: 'pointer',
    fontSize: '12px',
    padding: '7px 14px',
    transition: 'border-color 0.2s, color 0.2s',
    maxWidth: '240px',
    textAlign: 'left',
  },
  chatHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    padding: '6px 20px 0',
    flexShrink: 0,
  },
  chatHeaderRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  headerBtn: {
    background: 'transparent',
    border: '1px solid var(--border-color)',
    borderRadius: '8px',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: '11px',
    padding: '4px 10px',
    transition: 'color 0.15s',
  },
  errorBanner: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    margin: '12px auto 0',
    maxWidth: '800px',
    width: 'calc(100% - 32px)',
    padding: '12px 14px',
    borderRadius: '10px',
    backgroundColor: 'rgba(255, 90, 90, 0.12)',
    border: '1px solid rgba(255, 90, 90, 0.4)',
    color: '#ffb4b4',
    fontSize: '13px',
    lineHeight: '1.4',
  },
  errorText: { flex: 1 },
  errorClose: {
    background: 'none',
    border: 'none',
    color: 'inherit',
    cursor: 'pointer',
    fontSize: '14px',
    padding: '2px 6px',
  },
  messageList: {
    flex: 1,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
  introBox: {
    border: '1px dashed var(--border-color)',
    borderRadius: '12px',
    textAlign: 'center',
    maxWidth: '500px',
    color: 'var(--text-secondary)',
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  messageWrapper: {
    display: 'flex',
    width: '100%',
  },
  messageBubble: {
    padding: '12px 16px',
    borderRadius: '12px',
    fontSize: '14px',
    lineHeight: '1.5',
    wordBreak: 'break-word',
  },
  userBubble: {
    backgroundColor: '#ffffff',
    color: '#000000',
    borderRadius: '12px 12px 2px 12px',
  },
  assistantBubble: {
    background: 'var(--bg-secondary)',
    border: '1px solid var(--border-color)',
    borderRadius: '12px 12px 12px 2px',
    width: '100%',
  },
  assistantLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '8px',
  },
  assistantLabelDot: {
    display: 'inline-block',
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    backgroundColor: 'var(--text-secondary)',
    flexShrink: 0,
  },
  assistantLabelText: {
    fontSize: '10px',
    fontWeight: '600',
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    flex: 1,
  },
  copyMsgBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: '14px',
    padding: '0 4px',
    opacity: 0.6,
    lineHeight: 1,
    transition: 'opacity 0.15s',
  },
  messageContent: {
    whiteSpace: 'pre-wrap',
  },
  followupRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px',
    marginTop: '12px',
    paddingTop: '10px',
    borderTop: '1px solid rgba(129, 140, 248, 0.12)',
  },
  followupChip: {
    background: 'rgba(129, 140, 248, 0.06)',
    border: '1px solid rgba(129, 140, 248, 0.2)',
    borderRadius: '999px',
    color: 'rgba(200, 205, 255, 0.8)',
    cursor: 'pointer',
    fontSize: '12px',
    padding: '5px 12px',
    transition: 'background 0.15s, border-color 0.15s',
    textAlign: 'left',
  },
  thinkingDots: {
    display: 'flex',
    gap: '5px',
    alignItems: 'center',
    padding: '4px 0 8px',
  },
  inputForm: {
    backgroundColor: 'var(--bg-primary)',
  },
  inputWrapper: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '6px 6px 6px 12px',
    borderRadius: '24px',
    backgroundColor: 'var(--bg-secondary)',
    border: '1px solid var(--border-color)',
    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)',
    maxWidth: '800px',
    margin: '0 auto',
    width: '100%',
  },
  inputField: {
    flex: 1,
    background: 'none',
    border: 'none',
    outline: 'none',
    color: 'var(--text-primary)',
    fontSize: '14px',
  },
  iconBtn: {
    background: 'transparent',
    border: 'none',
    borderRadius: '8px',
    cursor: 'pointer',
    fontSize: '16px',
    padding: '4px 6px',
    transition: 'background 0.2s, color 0.2s',
    flexShrink: 0,
    lineHeight: 1,
  },
  sendBtn: {
    width: '36px',
    height: '36px',
    borderRadius: '50%',
    border: 'none',
    fontSize: '16px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    transition: 'background-color 0.2s',
    flexShrink: 0,
  },
  stopBtn: {
    width: '36px',
    height: '36px',
    borderRadius: '50%',
    border: '1px solid rgba(248, 113, 113, 0.4)',
    background: 'rgba(248, 113, 113, 0.1)',
    color: '#f87171',
    fontSize: '14px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    flexShrink: 0,
    transition: 'background 0.2s',
  },
  agentStepCard: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '8px',
    backgroundColor: 'rgba(167, 139, 250, 0.08)',
    border: '1px solid rgba(167, 139, 250, 0.22)',
    borderRadius: '8px',
    padding: '8px 12px',
    margin: '6px 0 12px',
  },
  agentStepIcon: {
    fontSize: '14px',
    animation: 'pulse 1.2s ease-in-out infinite',
  },
  agentStepText: {
    fontSize: '12px',
    color: '#c7d2fe',
    fontFamily: 'var(--font-sans)',
  },
  slashPopover: {
    position: 'absolute',
    bottom: 'calc(100% + 10px)',
    left: '0',
    right: '0',
    backgroundColor: 'var(--bg-secondary)',
    border: '1px solid var(--border-color)',
    borderRadius: '12px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    padding: '8px 0',
    zIndex: 1000,
    display: 'flex',
    flexDirection: 'column',
  },
  slashHeader: {
    fontSize: '9px',
    fontWeight: '700',
    letterSpacing: '0.12em',
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    padding: '6px 16px 8px',
    borderBottom: '1px solid var(--border-color)',
    marginBottom: '4px',
  },
  slashItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    background: 'none',
    border: 'none',
    padding: '10px 16px',
    textAlign: 'left',
    cursor: 'pointer',
    width: '100%',
    transition: 'background 0.15s',
  },
  slashCmdText: {
    fontSize: '13px',
    fontWeight: '600',
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-primary)',
  },
  slashCmdDesc: {
    fontSize: '12px',
    color: '#a3a3a3',
  },
  userCmdPrefix: {
    color: 'var(--text-muted)',
    fontWeight: '600',
    fontFamily: 'var(--font-mono)',
    marginRight: '6px',
  },
  loaderContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    height: '100%',
    backgroundColor: '#0a0a0a',
    gap: '16px',
    color: '#fff',
    userSelect: 'none',
  },
  loaderSpinner: {
    width: '40px',
    height: '40px',
    borderRadius: '50%',
    border: '2px solid rgba(255, 255, 255, 0.05)',
    borderTopColor: '#f4f4f5',
    animation: 'ideator-spin 0.8s linear infinite',
  },
  loaderText: {
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    color: '#a1a1aa',
    letterSpacing: '0.05em',
    animation: 'ideator-pulse 1.5s ease-in-out infinite',
  },
};

export default ChatArea;

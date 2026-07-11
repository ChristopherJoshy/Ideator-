import { useState, useEffect, useRef } from 'react';
import ToolTrace from './ToolTrace';
import MarkdownRenderer from './MarkdownRenderer';
import { apiFetch, getWebSocketUrl } from '../utils/api';

function useWindowSize() {
  const [width, setWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1200);
  useEffect(() => {
    const handleResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  return width < 768;
}

const SUGGESTIONS = [
  'Turn a daily frustration into a product idea',
  'Find a practical final-year project direction',
  'Pressure-test a startup concept I have',
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
  const chatEndRef = useRef(null);
  
  const isMobile = useWindowSize();

  useEffect(() => {
    if (activeChatId) {
      fetchMessages();
    } else {
      setMessages([]);
    }
  }, [activeChatId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessage]);

  const fetchMessages = async (chatId = activeChatId) => {
    try {
      const res = await apiFetch(`/api/chats/${chatId}/messages`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data);
      }
    } catch (err) {
      console.error('Failed to fetch messages:', err);
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!inputPrompt.trim() || loading || !user) return;

    const prompt = inputPrompt.trim();
    setInputPrompt('');
    setLoading(true);
    setErrorMsg(null);

    let chatId = activeChatId;
    if (!chatId) {
      try {
        const response = await apiFetch('/api/chats', { method: 'POST' });
        if (!response.ok) throw new Error('Could not create a chat');
        const chat = await response.json();
        chatId = chat.id || chat._id;
        onCreateChat(chatId);
      } catch (err) {
        console.error('Failed to create chat:', err);
        setLoading(false);
        setInputPrompt(prompt);
        return;
      }
    }

    // 1. Instantly append User's message locally
    const userMsg = {
      id: String(Math.random()),
      sender: 'user',
      content: prompt,
      timestamp: new Date().toISOString()
    };
    setMessages(prev => [...prev, userMsg]);

    // 2. Open WebSocket stream connection
    const sessionId = user.id || user._id;
    const wsUrl = getWebSocketUrl(`/api/chats/${chatId}/ws?session_id=${encodeURIComponent(sessionId)}`);
    
    // Prepare the structure for the streaming assistant response
    let currentAssistantMsg = {
      sender: 'assistant',
      content: '',
      tool_steps: []
    };
    setStreamingMessage(currentAssistantMsg);

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      // Send the user prompt to the server
      socket.send(JSON.stringify({ prompt, user_name: user.display_name }));
    };

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.event === 'narrative') {
        currentAssistantMsg.content += data.text + '\n\n';
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'tool_start') {
        currentAssistantMsg.tool_steps = [
          ...currentAssistantMsg.tool_steps,
          { tool: data.name, args: data.args, result: null }
        ];
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'tool_end') {
        currentAssistantMsg.tool_steps = currentAssistantMsg.tool_steps.map(step => {
          if (step.tool === data.name && !step.result) {
            return { ...step, result: data.result };
          }
          return step;
        });
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'delta') {
        currentAssistantMsg.content += data.text;
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'error') {
        setErrorMsg(data.text || 'Something went wrong while generating a response.');
        currentAssistantMsg.content += `\n\n⚠️ ${data.text || 'Something went wrong while generating a response.'}`;
        setStreamingMessage({ ...currentAssistantMsg });
      } else if (data.event === 'done') {
        socket.close();
        setMessages(prev => [...prev, { ...currentAssistantMsg, id: String(Math.random()) }]);
        setStreamingMessage(null);
        setLoading(false);
        fetchMessages(chatId); // Pull fresh DB state
      }
    };

    socket.onerror = (err) => {
      console.error('WebSocket connection error:', err);
      socket.close();
      setErrorMsg('We couldn’t reach the backend. Please make sure the server is running and try again.');
      currentAssistantMsg.content += '\n\n⚠️ Connection interrupted. Please check if backend is running.';
      setMessages(prev => [...prev, { ...currentAssistantMsg, id: String(Math.random()) }]);
      setStreamingMessage(null);
      setLoading(false);
    };
    
    socket.onclose = () => {
      if (loading) {
        setMessages(prev => [...prev, { ...currentAssistantMsg, id: String(Math.random()) }]);
        setStreamingMessage(null);
        setLoading(false);
      }
    };
  };

  return (
    <div style={styles.chatContainer}>
      {errorMsg && (
        <div style={styles.errorBanner} role="alert">
          <span style={styles.errorText}>⚠️ {errorMsg}</span>
          <button type="button" style={styles.errorClose} onClick={() => setErrorMsg(null)} aria-label="Dismiss error">✕</button>
        </div>
      )}
      {!activeChatId ? (
        <div style={styles.homeScreen}>
          <div style={styles.placeholderIcon}>💡</div>
          <div style={styles.eyebrow}>IDEATOR WORKSPACE</div>
          <h2 style={{ ...styles.homeTitle, fontSize: isMobile ? '32px' : '48px' }}>
            Good {getDayPart()}, {user?.display_name?.split(' ')[0] || 'there'}.
          </h2>
          <p style={styles.homeSubtitle}>Start with a rough thought — a frustration, a project, a half-formed startup. We’ll pressure-test it, sharpen it, and tell you what to build first.</p>
          <form style={styles.homeComposer} onSubmit={handleSend}>
            <textarea rows="3" placeholder="What are you curious about?" value={inputPrompt}
              onChange={(e) => setInputPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              style={styles.homeInput} disabled={loading} />
            <div style={styles.composerFooter}>
              <span style={styles.composerHint}>A new workspace opens when you send</span>
              <button type="submit" style={styles.homeSend} disabled={loading || !inputPrompt.trim()}>
                {loading ? 'Starting…' : 'Start exploring'}
              </button>
            </div>
          </form>
          <div style={styles.suggestionList}>
            {SUGGESTIONS.map((suggestion) => (
              <button key={suggestion} type="button" style={styles.suggestion} onClick={() => setInputPrompt(suggestion)}>
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          {/* Scrollable Message List */}
          <div style={{
            ...styles.messageList,
            padding: isMobile ? '16px' : '24px'
          }}>
            {messages.length === 0 && !streamingMessage && (
              <div style={{
                ...styles.introBox,
                margin: isMobile ? '20px auto' : '40px auto',
                padding: isMobile ? '16px' : '24px'
              }}>
                <h3 style={{ fontSize: isMobile ? '14px' : '16px' }}>Describe an idea and we’ll help you find and sharpen it</h3>
                <p style={{ fontSize: isMobile ? '12px' : '14px' }}>
                  Example: "A peer-to-peer file locker that proves ownership with blockchain metadata"
                </p>
              </div>
            )}
            
            {messages.map((msg) => (
              <div 
                key={msg.id} 
                style={{
                  ...styles.messageWrapper,
                  justifyContent: msg.sender === 'user' ? 'flex-end' : 'flex-start'
                }}
              >
                <div 
                  style={{
                    ...styles.messageBubble,
                    ...(msg.sender === 'user' ? styles.userBubble : styles.assistantBubble),
                    maxWidth: isMobile ? '90%' : '75%'
                  }}
                >
                  {msg.sender === 'assistant' && (
                    <div style={styles.assistantLabel}>
                      <span style={styles.assistantLabelDot} />
                      <span style={styles.assistantLabelText}>Ideator</span>
                    </div>
                  )}
                  {msg.sender === 'user' ? (
                    <div style={styles.messageContent}>{msg.content}</div>
                  ) : (
                    <MarkdownRenderer content={msg.content} />
                  )}
                  
                  {/* Render inline trace logs */}
                  {msg.tool_steps && msg.tool_steps.length > 0 && (
                    <ToolTrace steps={msg.tool_steps} />
                  )}
                </div>
              </div>
            ))}

            {/* SSE Stream Message Rendering */}
            {streamingMessage && (
              <div style={{ ...styles.messageWrapper, justifyContent: 'flex-start' }}>
                <div style={{ 
                  ...styles.messageBubble, 
                  ...styles.assistantBubble,
                  maxWidth: isMobile ? '90%' : '75%'
                }}>
                  <div style={styles.assistantLabel}>
                    <span style={{ ...styles.assistantLabelDot, animation: 'pulse 1.2s ease-in-out infinite' }} />
                    <span style={styles.assistantLabelText}>Ideator</span>
                  </div>
                  <MarkdownRenderer content={streamingMessage.content} />
                  {streamingMessage.tool_steps.length > 0 && (
                    <ToolTrace steps={streamingMessage.tool_steps} />
                  )}
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Prompt Entry Bar */}
          <form style={{
            ...styles.inputForm,
            padding: isMobile ? '12px 16px 16px 16px' : '16px 24px 24px 24px'
          }} onSubmit={handleSend}>
            <div style={styles.inputWrapper}>
              <input
                type="text"
                placeholder={loading ? "Generating ideas..." : "Type your concept/idea here..."}
                value={inputPrompt}
                onChange={(e) => setInputPrompt(e.target.value)}
                style={styles.inputField}
                disabled={loading}
              />
              <button 
                type="submit" 
                style={{
                  ...styles.sendBtn,
                  backgroundColor: loading || !inputPrompt.trim() ? 'var(--border-color)' : '#ffffff',
                  color: loading || !inputPrompt.trim() ? 'var(--text-muted)' : '#000000'
                }} 
                disabled={loading || !inputPrompt.trim()}
              >
                {loading ? '●' : '→'}
              </button>
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
  noChatPlaceholder: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    gap: '16px',
    color: 'var(--text-muted)',
    textAlign: 'center',
    padding: '24px',
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
  errorText: {
    flex: 1,
  },
  errorClose: {
    background: 'none',
    border: 'none',
    color: 'inherit',
    cursor: 'pointer',
    fontSize: '14px',
    padding: '2px 6px',
  },
  suggestionList: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
    justifyContent: 'center',
    marginTop: '16px',
    maxWidth: '680px',
  },
  suggestion: {
    background: 'transparent',
    border: '1px solid var(--border-color)',
    borderRadius: '999px',
    color: 'var(--text-secondary)',
    cursor: 'pointer',
    fontSize: '12px',
    padding: '8px 12px',
  },
  placeholderIcon: {
    display: 'none',
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
    background: 'linear-gradient(135deg, #0d0d1a 0%, #0a0f1e 100%)',
    border: '1px solid rgba(129, 140, 248, 0.25)',
    boxShadow: '0 2px 12px rgba(99, 102, 241, 0.08), inset 0 0 0 1px rgba(129, 140, 248, 0.05)',
    borderRadius: '12px 12px 12px 2px',
  },
  assistantLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '8px',
  },
  assistantLabelDot: {
    display: 'inline-block',
    width: '7px',
    height: '7px',
    borderRadius: '50%',
    background: 'linear-gradient(135deg, #818cf8, #c084fc)',
    boxShadow: '0 0 6px rgba(129, 140, 248, 0.8)',
    flexShrink: 0,
  },
  assistantLabelText: {
    fontSize: '10px',
    fontWeight: '600',
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    background: 'linear-gradient(90deg, #818cf8, #c084fc)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
    fontFamily: 'var(--font-mono)',
  },
  messageContent: {
    whiteSpace: 'pre-wrap',
  },
  inputForm: {
    backgroundColor: 'var(--bg-primary)',
  },
  inputWrapper: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '6px 6px 6px 16px',
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
  }
};

export default ChatArea;

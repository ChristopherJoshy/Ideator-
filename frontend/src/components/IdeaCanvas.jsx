import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { apiFetch } from '../utils/api';

const SCORE_LABELS = {
  novelty: 'Novelty',
  feasibility: 'Feasibility',
  moat: 'Moat Defensibility',
  market_signal: 'Market Signal',
  demo_ability: 'Demo-ability',
};

const SCORE_COLORS = {
  novelty: '#f59e0b',      // Amber
  feasibility: '#10b981',  // Emerald
  moat: '#a78bfa',         // Violet
  market_signal: '#3b82f6', // Blue
  demo_ability: '#fbbf24',  // Yellow
};

export default function IdeaCanvas({ chatId, onNodeDoubleClick }) {
  const [activeTab, setActiveTab] = useState('canvas'); // 'canvas' | 'map'
  const [canvas, setCanvas] = useState({
    value_prop: '',
    target_user: '',
    tech_stack: '',
    checklist: [],
    scores: { novelty: 0, feasibility: 0, moat: 0, market_signal: 0, demo_ability: 0 },
  });
  const [history, setHistory] = useState([]);
  const [selectedVersionIndex, setSelectedVersionIndex] = useState(-1); // -1 = current active
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // SVG mindmap pan/zoom state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 180, y: 180 });
  const [isPanning, setIsPanning] = useState(false);
  const startPanOffset = useRef({ x: 0, y: 0 });

  // Custom node positions for visual map
  const [nodes, setNodes] = useState([]);
  const [draggedNodeId, setDraggedNodeId] = useState(null);

  // Fetch canvas data
  const fetchCanvas = useCallback(async () => {
    if (!chatId) return;
    setLoading(true);
    try {
      const res = await apiFetch(`/api/chats/${chatId}/canvas`);
      if (res.ok) {
        const data = await res.json();
        setCanvas(data);
      }
      const histRes = await apiFetch(`/api/chats/${chatId}/canvas/history`);
      if (histRes.ok) {
        const histData = await histRes.json();
        setHistory(histData);
      }
    } catch (err) {
      console.error('Failed to load canvas:', err);
    } finally {
      setLoading(false);
    }
  }, [chatId]);

  useEffect(() => {
    fetchCanvas();
    setSelectedVersionIndex(-1);
  }, [chatId, fetchCanvas]);

  // Sync WebSocket updates directly from parent state
  const handleWsUpdate = useCallback((newCanvas) => {
    setCanvas(newCanvas);
    // Refresh history silently
    apiFetch(`/api/chats/${chatId}/canvas/history`)
      .then(res => res.ok && res.json())
      .then(histData => histData && setHistory(histData))
      .catch(console.error);
  }, [chatId]);

  // Expose updates for the websocket events via window listener
  useEffect(() => {
    const onCanvasUpdate = (e) => {
      if (e.detail && e.detail.chatId === chatId) {
        handleWsUpdate(e.detail.canvas);
      }
    };
    window.addEventListener('ideator_canvas_ws_update', onCanvasUpdate);
    return () => window.removeEventListener('ideator_canvas_ws_update', onCanvasUpdate);
  }, [chatId, handleWsUpdate]);

  // Handle local text edits
  const handleFieldChange = (field, val) => {
    if (selectedVersionIndex !== -1) return; // Read-only for old versions
    setCanvas(prev => ({ ...prev, [field]: val }));
  };

  // Sync edits to DB
  const saveCanvas = async (updatedObj = canvas) => {
    if (!chatId || selectedVersionIndex !== -1) return;
    setSaving(true);
    try {
      const res = await apiFetch(`/api/chats/${chatId}/canvas`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedObj),
      });
      if (res.ok) {
        const saved = await res.json();
        setCanvas(saved);
        // Refresh history
        const histRes = await apiFetch(`/api/chats/${chatId}/canvas/history`);
        if (histRes.ok) setHistory(await histRes.json());
      }
    } catch (err) {
      console.error('Failed to save canvas:', err);
    } finally {
      setSaving(false);
    }
  };

  // Handle checklist item toggles
  const handleChecklistToggle = (idx) => {
    if (selectedVersionIndex !== -1) return;
    const item = canvas.checklist[idx];
    let updatedItem = item;
    if (item.startsWith('[x] ')) {
      updatedItem = item.replace('[x] ', '[ ] ');
    } else if (item.startsWith('[ ] ')) {
      updatedItem = item.replace('[ ] ', '[x] ');
    } else {
      updatedItem = '[x] ' + item;
    }
    const newList = [...canvas.checklist];
    newList[idx] = updatedItem;
    const updatedCanvas = { ...canvas, checklist: newList };
    setCanvas(updatedCanvas);
    saveCanvas(updatedCanvas);
  };

  // Load selected historical version
  const handleSelectVersion = (idx) => {
    setSelectedVersionIndex(idx);
    if (idx === -1) {
      // Restore current active
      fetchCanvas();
    } else {
      setCanvas(history[idx]);
    }
  };

  // Build the Mind Map node graph data dynamically from canvas content
  useEffect(() => {
    if (!canvas) return;

    // Node layout generator
    const newNodes = [];
    const coreLabel = canvas.value_prop ? canvas.value_prop.substring(0, 20) + '…' : 'My Idea';
    
    // Core Root Node
    newNodes.push({ id: 'root', label: coreLabel, type: 'root', x: 0, y: 0 });

    // Target User Node
    if (canvas.target_user) {
      const userLabel = canvas.target_user.substring(0, 18) + '…';
      newNodes.push({ id: 'user', label: `🎯 ${userLabel}`, type: 'user', x: -140, y: -80 });
    }

    // Tech Stack Node
    if (canvas.tech_stack) {
      newNodes.push({ id: 'tech_root', label: '🛠️ Tech Stack', type: 'tech', x: 140, y: -80 });
      // Individual tech items as leaves
      const items = canvas.tech_stack.split(',').map(s => s.trim()).filter(Boolean);
      items.slice(0, 4).forEach((item, i) => {
        newNodes.push({
          id: `tech_leaf_${i}`,
          label: item,
          type: 'tech_leaf',
          x: 160 + (i * 20),
          y: -150 - (i * 50)
        });
      });
    }

    // Action checklist leaf nodes
    const listItems = canvas.checklist || [];
    listItems.slice(0, 4).forEach((item, i) => {
      const cleaned = item.replace(/^\[[ x]\]\s*/, '');
      const checked = item.startsWith('[x] ');
      newNodes.push({
        id: `action_${i}`,
        label: `${checked ? '✓' : '☐'} ${cleaned.substring(0, 16)}…`,
        type: 'action',
        x: -150 - (i * 15),
        y: 80 + (i * 50)
      });
    });

    setNodes(newNodes);
  }, [canvas]);

  // Concept Map interaction handlers
  const handlePointerDown = (e) => {
    if (e.target.tagName === 'svg') {
      setIsPanning(true);
      startPanOffset.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handlePointerMove = (e) => {
    if (isPanning) {
      setPan({
        x: e.clientX - startPanOffset.current.x,
        y: e.clientY - startPanOffset.current.y
      });
    } else if (draggedNodeId) {
      // Node dragging logic (update coordinates)
      const rect = e.currentTarget.getBoundingClientRect();
      const clientX = e.clientX - rect.left - pan.x;
      const clientY = e.clientY - rect.top - pan.y;
      
      setNodes(prev =>
        prev.map(node =>
          node.id === draggedNodeId
            ? { ...node, x: clientX / zoom, y: clientY / zoom }
            : node
        )
      );
    }
  };

  const handlePointerUp = () => {
    setIsPanning(false);
    setDraggedNodeId(null);
  };

  // Node Drag Handlers
  const handleNodeDragStart = (id, e) => {
    e.stopPropagation();
    setDraggedNodeId(id);
  };

  // Filter out tech leaves links
  const links = useMemo(() => {
    const list = [];
    const rootNode = nodes.find(n => n.id === 'root');
    if (!rootNode) return list;

    nodes.forEach(node => {
      if (node.id === 'root') return;
      if (node.id === 'user' || node.id === 'tech_root' || node.id.startsWith('action_')) {
        list.push({ source: 'root', target: node.id });
      } else if (node.id.startsWith('tech_leaf_')) {
        list.push({ source: 'tech_root', target: node.id });
      }
    });
    return list;
  }, [nodes]);

  const activeCanvas = canvas || {
    value_prop: '',
    target_user: '',
    tech_stack: '',
    checklist: [],
    scores: { novelty: 0, feasibility: 0, moat: 0, market_signal: 0, demo_ability: 0 },
  };

  return (
    <div style={styles.container}>
      {/* Tab Row */}
      <div style={styles.tabRow}>
        <button
          style={{ ...styles.tabBtn, ...(activeTab === 'canvas' ? styles.tabBtnActive : {}) }}
          onClick={() => setActiveTab('canvas')}
        >
          📋 Idea Canvas
        </button>
        <button
          style={{ ...styles.tabBtn, ...(activeTab === 'map' ? styles.tabBtnActive : {}) }}
          onClick={() => setActiveTab('map')}
        >
          🗺️ Visual Map
        </button>

        {/* Version selector */}
        {history.length > 0 && (
          <select
            value={selectedVersionIndex}
            onChange={(e) => handleSelectVersion(Number(e.target.value))}
            style={styles.versionSelect}
          >
            <option value="-1">Active Version (Latest)</option>
            {history.map((hist, i) => (
              <option key={i} value={i}>
                V{i + 1} — {new Date(hist.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </option>
            ))}
          </select>
        )}
      </div>

      <div style={styles.content}>
        {activeTab === 'canvas' ? (
          /* 📋 --- IDEA CANVAS PANEL --- */
          <div style={styles.scrollArea}>
            {loading && <div style={styles.statusMsg}>Loading canvas data…</div>}

            {/* Score gauges */}
            <div style={styles.scoresGrid}>
              {Object.entries(activeCanvas.scores || {}).map(([key, val]) => (
                <div key={key} style={styles.scoreCard}>
                  <div style={styles.scoreHeader}>
                    <span style={styles.scoreName}>{SCORE_LABELS[key] || key}</span>
                    <span style={{ ...styles.scoreVal, color: SCORE_COLORS[key] }}>
                      {val.toFixed(1)}/10
                    </span>
                  </div>
                  <div style={styles.gaugeTrack}>
                    <div
                      style={{
                        ...styles.gaugeFill,
                        width: `${Math.min(Math.max(val * 10, 0), 100)}%`,
                        backgroundColor: SCORE_COLORS[key],
                        boxShadow: `0 0 8px ${SCORE_COLORS[key]}80`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Value Prop Card */}
            <div style={styles.canvasCard}>
              <div style={styles.cardHeader}>💡 Core Value Proposition</div>
              <textarea
                value={activeCanvas.value_prop || ''}
                onChange={(e) => handleFieldChange('value_prop', e.target.value)}
                onBlur={() => saveCanvas()}
                placeholder="What solves the problem? Explain the main concept..."
                style={styles.cardInput}
                disabled={selectedVersionIndex !== -1}
                rows={3}
              />
            </div>

            {/* Target User Card */}
            <div style={styles.canvasCard}>
              <div style={styles.cardHeader}>🎯 Target User & Jobs-to-be-Done</div>
              <textarea
                value={activeCanvas.target_user || ''}
                onChange={(e) => handleFieldChange('target_user', e.target.value)}
                onBlur={() => saveCanvas()}
                placeholder="Who has this pain? What job are they hiring this to do?"
                style={styles.cardInput}
                disabled={selectedVersionIndex !== -1}
                rows={2}
              />
            </div>

            {/* Stack Card */}
            <div style={styles.canvasCard}>
              <div style={styles.cardHeader}>🛠️ Recommended Stack / Components</div>
              <textarea
                value={activeCanvas.tech_stack || ''}
                onChange={(e) => handleFieldChange('tech_stack', e.target.value)}
                onBlur={() => saveCanvas()}
                placeholder="React, FastAPI, Qdrant, sensors, etc..."
                style={styles.cardInput}
                disabled={selectedVersionIndex !== -1}
                rows={2}
              />
            </div>

            {/* Checklist items */}
            {activeCanvas.checklist && activeCanvas.checklist.length > 0 && (
              <div style={styles.canvasCard}>
                <div style={styles.cardHeader}>🏃 Actionable Next Steps</div>
                <div style={styles.checklistGrid}>
                  {activeCanvas.checklist.map((item, idx) => {
                    const checked = item.startsWith('[x] ');
                    const label = item.replace(/^\[[ x]\]\s*/, '');
                    return (
                      <div
                        key={idx}
                        style={{ ...styles.checkItem, opacity: checked ? 0.5 : 1 }}
                        onClick={() => handleChecklistToggle(idx)}
                      >
                        <span style={styles.checkbox}>{checked ? '✓' : '☐'}</span>
                        <span style={{ ...styles.checkLabel, textDecoration: checked ? 'line-through' : 'none' }}>
                          {label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            
            {saving && <div style={styles.saveIndicator}>Saving changes…</div>}
          </div>
        ) : (
          /* 🗺️ --- INTERACTIVE CONCEPT MIND MAP --- */
          <div
            style={styles.mapContainer}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
          >
            {/* Zoom / Pan controls */}
            <div style={styles.mapToolbar}>
              <button style={styles.toolbarBtn} onClick={() => setZoom(z => Math.max(z - 0.1, 0.4))}>−</button>
              <span style={styles.zoomLabel}>{Math.round(zoom * 100)}%</span>
              <button style={styles.toolbarBtn} onClick={() => setZoom(z => Math.min(z + 0.1, 2.5))}>+</button>
              <button style={styles.toolbarBtn} onClick={() => { setZoom(1); setPan({ x: 180, y: 180 }); }}>Reset</button>
            </div>

            <svg style={styles.svg}>
              <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
                {/* Connection lines */}
                {links.map((link, idx) => {
                  const sourceNode = nodes.find(n => n.id === link.source);
                  const targetNode = nodes.find(n => n.id === link.target);
                  if (!sourceNode || !targetNode) return null;
                  return (
                    <line
                      key={idx}
                      x1={sourceNode.x}
                      y1={sourceNode.y}
                      x2={targetNode.x}
                      y2={targetNode.y}
                      stroke="rgba(255, 255, 255, 0.12)"
                      strokeWidth="2"
                    />
                  );
                })}

                {/* Draggable Mind Map Nodes */}
                {nodes.map((node) => {
                  const isRoot = node.type === 'root';
                  const borderCol = isRoot
                    ? '#818cf8'
                    : node.type === 'user'
                    ? '#38bdf8'
                    : node.type === 'tech'
                    ? '#10b981'
                    : 'rgba(255, 255, 255, 0.1)';

                  return (
                    <g
                      key={node.id}
                      transform={`translate(${node.x}, ${node.y})`}
                      onPointerDown={(e) => handleNodeDragStart(node.id, e)}
                      onDoubleClick={() => onNodeDoubleClick(node.label.replace(/^✓\s*|^☐\s*|^🎯\s*|^🛠️\s*/, ''))}
                      style={{ cursor: 'grab' }}
                    >
                      <rect
                        x="-75"
                        y="-20"
                        width="150"
                        height="40"
                        rx="8"
                        fill={isRoot ? '#6366f1' : '#14141d'}
                        stroke={borderCol}
                        strokeWidth={isRoot ? '2' : '1'}
                      />
                      <text
                        x="0"
                        y="5"
                        textAnchor="middle"
                        fill="#ffffff"
                        fontSize="10"
                        fontFamily="var(--font-sans)"
                        style={{ userSelect: 'none' }}
                      >
                        {node.label}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
            <div style={styles.mapTip}>Double-click nodes to ask Ideator about them. Drag nodes to re-arrange.</div>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    width: '100%',
    backgroundColor: '#07070a',
    borderLeft: '1px solid var(--border-color)',
    overflow: 'hidden',
  },
  tabRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    padding: '12px 16px',
    borderBottom: '1px solid var(--border-color)',
    flexShrink: 0,
    backgroundColor: 'var(--bg-secondary)',
  },
  tabBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    fontSize: '13px',
    fontWeight: '600',
    padding: '6px 12px',
    borderRadius: '6px',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  tabBtnActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    color: 'var(--text-primary)',
  },
  versionSelect: {
    marginLeft: 'auto',
    backgroundColor: '#111116',
    border: '1px solid var(--border-color)',
    borderRadius: '6px',
    color: '#a3a3a3',
    fontSize: '11px',
    padding: '3px 8px',
    outline: 'none',
  },
  content: {
    flex: 1,
    overflow: 'hidden',
    position: 'relative',
  },
  scrollArea: {
    height: '100%',
    overflowY: 'auto',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  statusMsg: {
    textAlign: 'center',
    fontSize: '13px',
    color: 'var(--text-muted)',
  },
  saveIndicator: {
    position: 'absolute',
    bottom: '12px',
    right: '16px',
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    border: '1px solid var(--border-color)',
    color: 'var(--text-muted)',
    fontSize: '11px',
    padding: '4px 8px',
    borderRadius: '6px',
    pointerEvents: 'none',
  },
  scoresGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr',
    gap: '10px',
    background: 'rgba(255, 255, 255, 0.02)',
    border: '1px solid rgba(255, 255, 255, 0.04)',
    borderRadius: '10px',
    padding: '12px',
  },
  scoreCard: {
    display: 'flex',
    flexDirection: 'column',
    gap: '5px',
  },
  scoreHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '11px',
    fontWeight: '600',
  },
  scoreName: {
    color: '#9ca3af',
  },
  scoreVal: {
    fontFamily: 'var(--font-mono)',
  },
  gaugeTrack: {
    height: '6px',
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  gaugeFill: {
    height: '100%',
    borderRadius: '3px',
    transition: 'width 0.6s cubic-bezier(0.1, 0.7, 0.1, 1)',
  },
  canvasCard: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    background: 'rgba(255, 255, 255, 0.01)',
    border: '1px solid rgba(255, 255, 255, 0.04)',
    borderRadius: '10px',
    padding: '14px',
  },
  cardHeader: {
    fontSize: '12px',
    fontWeight: '700',
    letterSpacing: '0.04em',
    color: '#e2e8f0',
    fontFamily: 'var(--font-mono)',
    textTransform: 'uppercase',
  },
  cardInput: {
    background: 'transparent',
    border: 'none',
    color: '#d1d5db',
    fontSize: '13px',
    lineHeight: '1.5',
    outline: 'none',
    resize: 'none',
    fontFamily: 'var(--font-sans)',
    width: '100%',
  },
  checklistGrid: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  checkItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    cursor: 'pointer',
    padding: '4px 0',
  },
  checkbox: {
    fontFamily: 'var(--font-mono)',
    fontSize: '15px',
    color: '#818cf8',
    userSelect: 'none',
  },
  checkLabel: {
    fontSize: '13px',
    color: '#d1d5db',
  },
  /* Map View Styles */
  mapContainer: {
    position: 'relative',
    width: '100%',
    height: '100%',
    overflow: 'hidden',
    userSelect: 'none',
  },
  svg: {
    width: '100%',
    height: '100%',
    display: 'block',
    background: '#040407',
  },
  mapToolbar: {
    position: 'absolute',
    top: '12px',
    right: '12px',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    backgroundColor: '#111116',
    border: '1px solid var(--border-color)',
    borderRadius: '8px',
    padding: '4px',
    zIndex: 10,
  },
  toolbarBtn: {
    width: '24px',
    height: '24px',
    borderRadius: '4px',
    border: 'none',
    backgroundColor: 'rgba(255,255,255,0.06)',
    color: '#fff',
    cursor: 'pointer',
    fontSize: '14px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  zoomLabel: {
    fontSize: '11px',
    color: '#a3a3a3',
    padding: '0 4px',
    minWidth: '38px',
    textAlign: 'center',
  },
  mapTip: {
    position: 'absolute',
    bottom: '12px',
    left: '12px',
    color: 'var(--text-muted)',
    fontSize: '10px',
    pointerEvents: 'none',
  },
};

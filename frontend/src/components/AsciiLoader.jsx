import { useEffect, useState, useRef } from 'react';

/* ─────────────────────────────────────────────────
   Large pixel-art "I D E A T O R" built from block
   characters. Each letter assembled column-by-column
   ───────────────────────────────────────────────── */
const LOGO_LINES = [
  '  ██╗██████╗ ███████╗ █████╗ ████████╗ ██████╗ ██████╗ ',
  '  ██║██╔══██╗██╔════╝██╔══██╗╚══██╔══╝██╔═══██╗██╔══██╗',
  '  ██║██║  ██║█████╗  ███████║   ██║   ██║   ██║██████╔╝',
  '  ██║██║  ██║██╔══╝  ██╔══██║   ██║   ██║   ██║██╔══██╗',
  '  ██║██████╔╝███████╗██║  ██║   ██║   ╚██████╔╝██║  ██║',
  '  ╚═╝╚═════╝ ╚══════╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝',
];

/* Tagline that types itself */
const TAGLINE = '// where ideas become reality';

/* Matrix rain characters */
const MATRIX_CHARS = 'アイウエオカキクケコサシスセソタチツテトナニヌネノ01IDEATOR∑∂∇λΩ∞█▓▒░';

/* Status messages that sequence through */
const PHASES = [
  { at: 0,    msg: 'Initialising engine...' },
  { at: 1200, msg: 'Loading knowledge base...' },
  { at: 2800, msg: 'Warming up ideation core...' },
  { at: 4400, msg: 'Almost ready...' },
];

/* ─────────────────────────────────────────────────────────────────── */

function useAnimFrame(interval = 50) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), interval);
    return () => clearInterval(id);
  }, [interval]);
  return tick;
}

/* Matrix rain column state */
function useMatrixRain(cols, rows) {
  const dropsRef = useRef([]);
  const charsRef = useRef([]);
  const tick = useAnimFrame(80);

  if (dropsRef.current.length !== cols) {
    dropsRef.current = Array.from({ length: cols }, () => Math.floor(Math.random() * -rows));
    charsRef.current = Array.from({ length: cols }, () =>
      Array.from({ length: rows }, () => MATRIX_CHARS[Math.floor(Math.random() * MATRIX_CHARS.length)])
    );
  }

  useEffect(() => {
    dropsRef.current = dropsRef.current.map((y, i) => {
      charsRef.current[i] = charsRef.current[i].map((c, row) =>
        Math.random() < 0.08 ? MATRIX_CHARS[Math.floor(Math.random() * MATRIX_CHARS.length)] : c
      );
      return y >= rows + 5 ? Math.floor(Math.random() * -10) : y + 1;
    });
  }, [tick, cols, rows]);

  return { drops: dropsRef.current, chars: charsRef.current, tick };
}

/* ─────────────────────────────────────────────────────────────────── */

const COLS = 28;
const ROWS = 12;

export default function AsciiLoader({ text = 'Loading Ideator' }) {
  const startRef = useRef(Date.now());
  const tick80 = useAnimFrame(80);
  const tick40 = useAnimFrame(40);
  const { drops, chars } = useMatrixRain(COLS, ROWS);

  /* Elapsed time for progress + phases */
  const elapsed = Date.now() - startRef.current;
  const progress = Math.min(elapsed / 6000, 1); // 0 → 1 over 6 s

  /* Current status phase */
  const phase = [...PHASES].reverse().find(p => elapsed >= p.at) ?? PHASES[0];

  /* Typewriter effect on tagline */
  const tagLen = Math.min(Math.floor(elapsed / 50), TAGLINE.length);
  const visibleTag = TAGLINE.slice(0, tagLen);

  /* Logo reveal — characters stream in column by column */
  const logoRevealCols = Math.floor(progress * 56); // logo is ~56 chars wide

  /* Breathing glow on logo */
  const breathe = 0.5 + 0.5 * Math.sin((tick80 * 80) / 600);
  const glowOpacity = 0.3 + breathe * 0.5;

  /* Cursor blink */
  const cursor = tick40 % 16 < 8 ? '█' : ' ';

  /* Spinner ring */
  const RING = ['◜', '◝', '◞', '◟'];
  const ring = RING[tick80 % RING.length];

  /* Scanline Y for the horizontal sweep */
  const scanY = (tick80 % (ROWS + 4)) - 2;

  /* Build the left matrix rain panel as a string grid */
  const matrixGrid = Array.from({ length: ROWS }, (_, row) => {
    return Array.from({ length: COLS }, (_, col) => {
      const dropY = drops[col];
      const distFromHead = dropY - row;
      if (distFromHead === 0) return { ch: chars[col][row] ?? '█', bright: true, head: true };
      if (distFromHead > 0 && distFromHead < 6) return { ch: chars[col][row] ?? ' ', bright: false, fade: 6 - distFromHead };
      return { ch: ' ', bright: false, fade: 0 };
    });
  });

  /* scanline row highlight */
  const isScanRow = (row) => row === scanY || row === scanY + 1;

  return (
    <div style={S.wrap}>
      {/* ── Matrix rain panel (left decoration) ── */}
      <div style={S.matrixPane} className="desktop-only" aria-hidden="true">
        {matrixGrid.map((row, ri) => (
          <div key={ri} style={S.matrixRow}>
            {row.map((cell, ci) => {
              const opacity = cell.head ? 1 : cell.fade ? (cell.fade / 6) * 0.7 : 0;
              const color = cell.head ? '#ffffff' : '#2d2d2d';
              const shadow = cell.head ? '0 0 8px #fff, 0 0 2px #fff' : 'none';
              const scanBoost = isScanRow(ri) && cell.ch !== ' ' ? 0.15 : 0;
              return (
                <span
                  key={ci}
                  style={{
                    ...S.matrixCell,
                    opacity: Math.min(opacity + scanBoost, 1),
                    color,
                    textShadow: shadow,
                  }}
                >
                  {cell.ch !== ' ' ? cell.ch : '\u00a0'}
                </span>
              );
            })}
          </div>
        ))}
      </div>

      {/* ── Main center panel ── */}
      <div style={S.center}>
        {/* Corner decorations */}
        <div style={S.cornerTL} aria-hidden="true">┌─────</div>
        <div style={S.cornerTR} aria-hidden="true">─────┐</div>

        {/* IDEATOR pixel logo */}
        <div style={S.logoWrap} aria-label="IDEATOR">
          {LOGO_LINES.map((line, li) => (
            <div key={li} style={S.logoLine} aria-hidden="true">
              {line.split('').map((ch, ci) => {
                const revealed = ci <= logoRevealCols;
                const isBlock = ch === '█' || ch === '╗' || ch === '╔' || ch === '║' || ch === '╝' || ch === '╚' || ch === '═' || ch === '╠' || ch === '╣' || ch === '╦' || ch === '╩' || ch === '╬';
                /* Slight per-column shimmer */
                const shimmer = isBlock && Math.sin((tick80 * 0.4) + ci * 0.18 + li * 0.7);
                const bright = 0.85 + (shimmer > 0.7 ? 0.15 : 0);
                return (
                  <span
                    key={ci}
                    style={{
                      color: revealed ? `rgba(255,255,255,${bright})` : 'transparent',
                      textShadow: revealed && isBlock
                        ? `0 0 ${8 + shimmer * 6}px rgba(255,255,255,${glowOpacity}), 0 0 2px rgba(255,255,255,0.6)`
                        : 'none',
                      transition: 'color 0.06s, text-shadow 0.06s',
                    }}
                  >
                    {ch === ' ' ? '\u00a0' : ch}
                  </span>
                );
              })}
            </div>
          ))}
        </div>

        {/* Tagline */}
        <div style={S.tagline} aria-live="polite">
          <span style={S.taglineText}>{visibleTag}</span>
          <span style={{ ...S.taglineCursor, opacity: tagLen < TAGLINE.length ? 1 : tick40 % 16 < 8 ? 0.9 : 0 }}>
            {cursor}
          </span>
        </div>

        {/* Divider */}
        <div style={S.divider} aria-hidden="true">
          {'─'.repeat(52)}
        </div>

        {/* Progress bar */}
        <div style={S.progressTrack} role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ ...S.progressFill, width: `${progress * 100}%` }} />
          <div style={{ ...S.progressGlow, width: `${progress * 100}%` }} />
        </div>

        {/* Status line */}
        <div style={S.statusRow}>
          <span style={S.ring}>{ring}</span>
          <span style={S.statusText}>{phase.msg}</span>
          <span style={S.pct}>{Math.round(progress * 100)}%</span>
        </div>

        {/* Corner decorations */}
        <div style={S.cornerBL} aria-hidden="true">└─────</div>
        <div style={S.cornerBR} aria-hidden="true">─────┘</div>
      </div>

      {/* ── Mirror matrix rain panel (right) ── */}
      <div style={{ ...S.matrixPane, transform: 'scaleX(-1)' }} className="desktop-only" aria-hidden="true">
        {matrixGrid.map((row, ri) => (
          <div key={ri} style={S.matrixRow}>
            {row.map((cell, ci) => {
              const opacity = cell.head ? 1 : cell.fade ? (cell.fade / 6) * 0.7 : 0;
              const color = cell.head ? '#ffffff' : '#2d2d2d';
              const shadow = cell.head ? '0 0 8px #fff, 0 0 2px #fff' : 'none';
              const scanBoost = isScanRow(ri) && cell.ch !== ' ' ? 0.15 : 0;
              return (
                <span
                  key={ci}
                  style={{
                    ...S.matrixCell,
                    opacity: Math.min(opacity + scanBoost, 1),
                    color,
                    textShadow: shadow,
                  }}
                >
                  {cell.ch !== ' ' ? cell.ch : '\u00a0'}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Styles ──────────────────────────────────────────────────────── */
const S = {
  wrap: {
    display: 'flex',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100vh',
    width: '100vw',
    backgroundColor: '#000',
    gap: '0px',
    overflow: 'hidden',
    position: 'relative',
  },

  /* Matrix rain columns */
  matrixPane: {
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
    opacity: 0.6,
    userSelect: 'none',
    flexShrink: 0,
  },
  matrixRow: {
    display: 'flex',
    flexDirection: 'row',
    lineHeight: '1.35',
  },
  matrixCell: {
    fontFamily: '"JetBrains Mono", "Courier New", monospace',
    fontSize: '11px',
    width: '10px',
    display: 'inline-block',
    textAlign: 'center',
    transition: 'opacity 0.08s',
  },

  /* Center block */
  center: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '10px',
    padding: 'var(--ascii-center-padding, 24px 28px)',
    position: 'relative',
  },

  /* Corner box art */
  cornerTL: {
    position: 'absolute', top: 0, left: 0,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 'var(--ascii-corner-font-size, 12px)', color: '#333', userSelect: 'none',
  },
  cornerTR: {
    position: 'absolute', top: 0, right: 0,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 'var(--ascii-corner-font-size, 12px)', color: '#333', userSelect: 'none',
  },
  cornerBL: {
    position: 'absolute', bottom: 0, left: 0,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 'var(--ascii-corner-font-size, 12px)', color: '#333', userSelect: 'none',
  },
  cornerBR: {
    position: 'absolute', bottom: 0, right: 0,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 'var(--ascii-corner-font-size, 12px)', color: '#333', userSelect: 'none',
  },

  /* Logo */
  logoWrap: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 0,
    userSelect: 'none',
  },
  logoLine: {
    fontFamily: '"JetBrains Mono", "Courier New", monospace',
    fontSize: 'var(--ascii-logo-font-size, 13px)',
    lineHeight: '1.2',
    letterSpacing: '0',
    whiteSpace: 'pre',
  },

  /* Tagline */
  tagline: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 'var(--ascii-tagline-font-size, 12px)',
    color: '#555',
    letterSpacing: '0.08em',
    marginTop: '4px',
    height: '18px',
    display: 'flex',
    alignItems: 'center',
  },
  taglineText: {
    color: '#444',
  },
  taglineCursor: {
    color: '#888',
    transition: 'opacity 0.1s',
  },

  /* Divider */
  divider: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 'var(--ascii-divider-font-size, 11px)',
    color: '#1a1a1a',
    letterSpacing: '0',
    userSelect: 'none',
    marginTop: '2px',
  },

  /* Progress */
  progressTrack: {
    width: '440px',
    maxWidth: '90vw',
    height: '2px',
    background: '#111',
    borderRadius: '999px',
    overflow: 'hidden',
    position: 'relative',
    marginTop: '4px',
  },
  progressFill: {
    height: '100%',
    background: 'linear-gradient(90deg, #333 0%, #fff 100%)',
    borderRadius: '999px',
    transition: 'width 0.12s linear',
    position: 'absolute',
    top: 0, left: 0,
  },
  progressGlow: {
    height: '100%',
    background: 'linear-gradient(90deg, transparent 60%, rgba(255,255,255,0.6) 100%)',
    borderRadius: '999px',
    position: 'absolute',
    top: 0, left: 0,
    filter: 'blur(4px)',
    transition: 'width 0.12s linear',
  },

  /* Status */
  statusRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: '11px',
    color: '#333',
    letterSpacing: '0.06em',
    marginTop: '2px',
  },
  ring: {
    fontSize: '13px',
    color: '#555',
    display: 'inline-block',
    lineHeight: 1,
  },
  statusText: {
    flex: 1,
    color: '#3a3a3a',
    minWidth: '200px',
  },
  pct: {
    color: '#2a2a2a',
    fontVariantNumeric: 'tabular-nums',
  },
};

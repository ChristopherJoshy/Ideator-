import { useState, useEffect } from 'react';
import { Burger } from '@mantine/core';
import LoginModal from './components/LoginModal';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import AsciiLoader from './components/AsciiLoader';
import { apiFetch, normalizeUser } from './utils/api';

function useWindowSize() {
  const [width, setWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1200);
  
  useEffect(() => {
    const handleResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  
  return width < 768; // Returns true if screen is mobile/tablet
}

function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [activeChatId, setActiveChatId] = useState(null);
  const [loadingUser, setLoadingUser] = useState(true);
  const [ready, setReady] = useState(false);
  const isMobile = useWindowSize();
  const [isSidebarOpen, setIsSidebarOpen] = useState(!isMobile);

  // Verify session on mount
  useEffect(() => {
    const minTimer = setTimeout(() => setReady(true), 6000);
    return () => clearTimeout(minTimer);
  }, []);

  useEffect(() => {
    const checkSession = async () => {
      // First check LocalStorage to restore sessions immediately
      const savedUser = localStorage.getItem('ideator_user');
      if (savedUser) {
        try {
          const user = normalizeUser(JSON.parse(savedUser));
          setCurrentUser(user);
          localStorage.setItem('ideator_user', JSON.stringify(user));
        } catch (e) {
          console.error('Failed to parse saved user:', e);
        }
      }

      try {
        const res = await apiFetch('/api/auth/me');
        if (res.ok) {
          const user = normalizeUser(await res.json());
          const normalizedUser = normalizeUser(user);
          setCurrentUser(normalizedUser);
          localStorage.setItem('ideator_user', JSON.stringify(normalizedUser));
        } else if (res.status === 401) {
          // If server reports unauthorized, clear LocalStorage
          setCurrentUser(null);
          localStorage.removeItem('ideator_user');
        }
      } catch (err) {
        console.log('No active session found or backend offline.');
      } finally {
        setLoadingUser(false);
      }
    };
    checkSession();
  }, []);

  const handleLogout = async () => {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (err) {
      console.error('Logout request failed:', err);
    } finally {
      setCurrentUser(null);
      setActiveChatId(null);
      setIsSidebarOpen(false);
      localStorage.removeItem('ideator_user');
    }
  };

  if (loadingUser || !ready) {
    return <AsciiLoader text="Loading Ideator" />;
  }

  return (
    <div style={styles.appContainer} className="app-shell">
      {/* Header */}
      <header style={styles.header}>
        <div style={styles.logoSection}>
          {currentUser && (
            <Burger
              opened={isSidebarOpen}
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              aria-label={isSidebarOpen ? "Collapse sidebar" : "Open sidebar"}
            />
          )}
          <img src="/ideator-logo.jpg" alt="Ideator Logo" style={styles.logo} />
          <h1 style={styles.title}>IDEATOR</h1>
        </div>
      </header>

      {/* Main Screen Layout */}
      {!currentUser ? (
        <LoginModal onLoginSuccess={(user) => {
          setCurrentUser(user);
          localStorage.setItem('ideator_user', JSON.stringify(user));
        }} />
      ) : (
        <div style={styles.mainContent}>
          {/* Sidebar - Collapsible on desktop (in-flow) and an overlay drawer on mobile */}
          <div style={{
            ...styles.sidebarWrapper,
            ...(isSidebarOpen ? {} : styles.sidebarHidden),
            ...(isSidebarOpen && isMobile ? styles.sidebarMobile : {}),
          }} className="sidebarWrapper">
            <Sidebar 
              activeChatId={activeChatId}
              onSelectChat={(id) => {
                setActiveChatId(id);
                if (isMobile) setIsSidebarOpen(false); // Close drawer on selection
              }}
              onCreateChat={(id) => {
                setActiveChatId(id);
                if (isMobile) setIsSidebarOpen(false); // Close drawer on creation
              }}
              onDeleteChat={(id) => {
                if (id === activeChatId) setActiveChatId(null);
              }}
              user={currentUser}
              onLogout={handleLogout}
            />
          </div>

          {/* Click block backdrop when drawer is open on mobile */}
          {isMobile && isSidebarOpen && (
            <div 
              style={styles.backdrop} 
              onClick={() => setIsSidebarOpen(false)}
            />
          )}

          {/* Chat main space */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%' }}>
            <ChatArea
              activeChatId={activeChatId}
              user={currentUser}
              onCreateChat={(id) => {
                setActiveChatId(id);
                if (isMobile) setIsSidebarOpen(false);
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

const styles = {
  appContainer: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    height: '100dvh',
    width: '100%',
    maxWidth: '100%',
    overflow: 'hidden',
    backgroundColor: 'var(--bg-primary)',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '0 16px',
    paddingTop: 'env(safe-area-inset-top, 0px)',
    height: '64px',
    borderBottom: '1px solid var(--border-color)',
    backgroundColor: 'var(--bg-secondary)',
    zIndex: 200,
  },
  logoSection: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  logo: {
    width: '32px',
    height: '32px',
    borderRadius: '4px',
    border: '1px solid var(--border-color)',
  },
  title: {
    fontSize: '18px',
    fontWeight: '700',
    letterSpacing: '2px',
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-primary)',
  },
  mainContent: {
    display: 'flex',
    flex: 1,
    position: 'relative',
    overflow: 'hidden',
  },
  sidebarWrapper: {
    display: 'flex',
    height: '100%',
    width: '260px',
    zIndex: 100,
    transition: 'transform 0.3s ease',
  },
  sidebarMobile: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    transform: 'translateX(0)',
    boxShadow: '4px 0 24px rgba(0, 0, 0, 0.6)',
  },
  sidebarHidden: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    transform: 'translateX(-100%)',
  },
  backdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    backdropFilter: 'blur(4px)',
    zIndex: 90,
  },
};

export default App;

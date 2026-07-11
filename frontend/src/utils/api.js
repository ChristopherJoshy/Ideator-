export const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '');

export const getWebSocketUrl = (path) => {
  const baseUrl = (import.meta.env.VITE_WS_URL || API_BASE_URL).replace(/^http/, 'ws');
  return `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
};

export const getAuthHeaders = () => {
  const headers = {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': '1',
  };
  
  const savedUser = localStorage.getItem('ideator_user');
  if (savedUser) {
    try {
      const user = JSON.parse(savedUser);
      const sessionId = user?.id || user?._id;
      if (sessionId) {
        headers['Authorization'] = `Session ${sessionId}`;
      }
    } catch (e) {
      console.error('Failed to parse user session:', e);
    }
  }
  return headers;
};

export const normalizeUser = (user) => {
  if (!user) return null;
  const id = user.id || user._id;
  return id ? { ...user, id } : user;
};

export const apiFetch = async (endpoint, options = {}) => {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  
  // Merge headers safely
  const mergedHeaders = {
    ...getAuthHeaders(),
    ...options.headers,
  };
  
  // If the body is a FormData, we should let fetch set the Content-Type automatically
  if (options.body instanceof FormData) {
    delete mergedHeaders['Content-Type'];
  }
  
  const fetchOptions = {
    ...options,
    headers: mergedHeaders,
    credentials: 'include', // Include session cookies for cross-origin requests
  };
  
  return fetch(url, fetchOptions);
};

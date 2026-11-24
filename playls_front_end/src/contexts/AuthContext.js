import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { API_BASE, api } from '../api';
import { IS_DEMO } from '../demo';
import { setTelemetryEnabled } from '../telemetry';

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

// The session is an httpOnly cookie set by the backend after Spotify login, so the
// frontend never sees the token. It asks the backend who is logged in instead.
export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Analytics only for users who opted in
  useEffect(() => { setTelemetryEnabled(user?.analytics_consent === true); }, [user]);

  // Merge fields into the signed-in user (e.g. after changing the analytics consent)
  const updateUser = (fields) => setUser((u) => (u ? { ...u, ...fields } : u));

  useEffect(() => {
    // Tokens used to be kept in localStorage; drop any left over from old sessions
    localStorage.removeItem('userId');
    localStorage.removeItem('accessToken');

    axios.get(`${API_BASE}/auth/me`)
      .then((response) => setUser(response.data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  // Demo mode: start (or resume) a demo account; errors (e.g. 503 "the demo is full") propagate
  const startDemo = async () => {
    await api.demoStart();
    const response = await axios.get(`${API_BASE}/auth/me`);
    setUser(response.data);
  };

  const login = async () => {
    if (IS_DEMO) return startDemo();
    try {
      const response = await axios.get(`${API_BASE}/auth/login`);
      const authUrl = response.data.auth_url;
      if (!authUrl) {
        console.error("No auth_url returned from backend");
        return;
      }
      window.location.href = authUrl;
    } catch (error) {
      console.error('Login failed:', error);
    }
  };

  // In the demo, logging out ends the demo (its account is deleted)
  const logout = async () => {
    try {
      if (IS_DEMO) await api.demoEnd().catch(() => {});
      else await axios.post(`${API_BASE}/auth/logout`);
    } finally {
      setUser(null);
    }
  };

  const value = {
    user,
    login,
    logout,
    loading,
    updateUser,
  };

  return (
    <AuthContext.Provider value={value}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

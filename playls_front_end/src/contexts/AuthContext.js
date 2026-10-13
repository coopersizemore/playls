import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { API_BASE } from '../api';

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

  useEffect(() => {
    // Tokens used to be kept in localStorage; drop any left over from old sessions
    localStorage.removeItem('userId');
    localStorage.removeItem('accessToken');

    axios.get(`${API_BASE}/auth/me`)
      .then((response) => setUser(response.data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async () => {
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

  const logout = async () => {
    try {
      await axios.post(`${API_BASE}/auth/logout`);
    } finally {
      setUser(null);
    }
  };

  const value = {
    user,
    login,
    logout,
    loading
  };

  return (
    <AuthContext.Provider value={value}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

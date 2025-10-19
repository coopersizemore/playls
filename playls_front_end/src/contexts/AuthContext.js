import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';

const BACKEND_URL = process.env.REDIRECT_URI || "http://localhost:8000";

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is already logged in
    const userId = localStorage.getItem('userId');
    const accessToken = localStorage.getItem('accessToken');
    
    if (userId && accessToken) {
      setUser({ id: userId, accessToken });
    }
    setLoading(false);
  }, []);

const login = async () => {
  try {
    const response = await axios.get(`${BACKEND_URL}/auth/login`);
    console.log("Login response:", response.data);
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


  const logout = () => {
    localStorage.removeItem('userId');
    localStorage.removeItem('accessToken');
    setUser(null);
  };

  const handleCallback = async (code, state) => {
    try {
      const response = await axios.get(`${BACKEND_URL}/auth/callback?code=${code}&state=${state}`);
      const { user_id, access_token } = response.data;
      
      localStorage.setItem('userId', user_id);
      localStorage.setItem('accessToken', access_token);
      setUser({ id: user_id, accessToken: access_token });
      
      return true;
    } catch (error) {
      console.error('Callback failed:', error);
      return false;
    }
  };

  const value = {
    user,
    setUser,
    login,
    logout,
    handleCallback,
    loading
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};


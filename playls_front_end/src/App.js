import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import Home from './components/Home';
import Login from './components/Login';
import Review from './components/Review';
import History from './components/History';
import Settings from './components/Settings';
import Restock from './components/Restock';
import AdminPicks from './components/AdminPicks';
import { RequireAuth } from './components/Layout';
import { AuthProvider } from './contexts/AuthContext';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#1DB954', // Spotify green
    },
    secondary: {
      main: '#191414', // Spotify black
    },
    background: {
      default: '#121212',
      paper: '#1E1E1E',
    },
    text: {
      primary: '#FFFFFF',
      secondary: '#B3B3B3',
    },
  },
  typography: {
    fontFamily: '"Circular", "Helvetica", "Arial", sans-serif',
  },
});

const authed = (element) => <RequireAuth>{element}</RequireAuth>;

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/rotation/:rotationId/review" element={authed(<Review />)} />
            <Route path="/rotation/:rotationId/history" element={authed(<History />)} />
            <Route path="/rotation/:rotationId/restock" element={authed(<Restock />)} />
            <Route path="/settings" element={authed(<Settings />)} />
            <Route path="/admin/picks" element={authed(<AdminPicks />)} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;

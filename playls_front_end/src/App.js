import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ColorModeProvider } from './colorMode';
import Home from './components/Home';
import Login from './components/Login';
import Review from './components/Review';
import History from './components/History';
import RotationPage from './components/RotationPage';
import Settings from './components/Settings';
import Restock from './components/Restock';
import AdminPicks from './components/AdminPicks';
import { RequireAuth } from './components/Layout';
import { AuthProvider } from './contexts/AuthContext';

// Admin-only and chart-heavy: loaded on demand so other pages don't carry it
const AdminStats = lazy(() => import('./components/AdminStats'));

const authed = (element) => <RequireAuth>{element}</RequireAuth>;

function App() {
  return (
    <ColorModeProvider>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/rotation/:rotationId" element={authed(<RotationPage />)} />
            <Route path="/rotation/:rotationId/review" element={authed(<Review />)} />
            <Route path="/rotation/:rotationId/history" element={authed(<History />)} />
            <Route path="/rotation/:rotationId/restock" element={authed(<Restock />)} />
            <Route path="/settings" element={authed(<Settings />)} />
            <Route path="/admin/picks" element={authed(<AdminPicks />)} />
            <Route path="/admin/stats" element={authed(<Suspense fallback={null}><AdminStats /></Suspense>)} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ColorModeProvider>
  );
}

export default App;

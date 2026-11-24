import React, { useState } from 'react';
import { Alert, Box, Button, Container, Link, Typography } from '@mui/material';
import { FastForward } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { api, errorMessage } from '../api';
import { parseUtc, Wordmark } from './Layout';
import { RotationVisual } from './Help';

const hoursLeft = (iso) => (iso ? Math.max(0, Math.ceil((parseUtc(iso) - new Date()) / 3600000)) : null);

// Landing page at /demo for visitors without a demo yet
export const DemoLanding = () => {
  const { login } = useAuth();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  const start = async () => {
    setStarting(true);
    setError('');
    try {
      await login();
    } catch (e) {
      setError(errorMessage(e, "Couldn't start the demo. Please try again."));
      setStarting(false);
    }
  };

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <Container maxWidth="sm" sx={{ pt: 10, textAlign: 'center' }}>
        <Typography variant="h3" component="h1" gutterBottom sx={{ fontWeight: 700, letterSpacing: '0.04em' }}>
          <Wordmark /> demo
        </Typography>
        <Box my={4}><RotationVisual showDue={false} /></Box>
        <Typography variant="h6" color="text.secondary" paragraph>
          Try PlayLS with sample playlists. No Spotify account needed.
        </Typography>
        <Typography color="text.secondary" paragraph>
          Review songs, restock, and skip ahead a day to watch songs come back around. Nothing touches
          Spotify, and the demo resets after 24 hours.
        </Typography>
        {error && <Alert severity="error" sx={{ mt: 2, textAlign: 'left' }}>{error}</Alert>}
        <Button variant="contained" size="large" onClick={start} disabled={starting} sx={{ mt: 3, px: 4, py: 1.5 }}>
          {starting ? 'Starting…' : 'Start the demo'}
        </Button>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 4 }}>
          Have access already? <Link href="/" underline="hover">Log in with Spotify</Link>
        </Typography>
      </Container>
    </Box>
  );
};

// Strip above every demo page: time left, Skip ahead a day, End demo
export const DemoBanner = () => {
  const { user, logout } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const left = hoursLeft(user?.demo_expires_at);

  const skipAhead = async () => {
    setBusy(true);
    setError('');
    try {
      await api.demoSkipAhead();
      // Every page's numbers depend on the clock; reloading is the simplest way to refresh them
      window.location.reload();
    } catch (e) {
      setError(errorMessage(e, "Couldn't skip ahead."));
      setBusy(false);
    }
  };

  const end = async () => {
    setBusy(true);
    await logout();
    window.location.assign('/demo');
  };

  return (
    <Box sx={{ bgcolor: 'surface.main', borderRadius: 2, px: 2, py: 1, mt: 1 }}>
      <Box display="flex" alignItems="center" flexWrap="wrap" columnGap={1} rowGap={0.5}>
        <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0 }}>
          <strong>Demo</strong>
          {left != null && ` · resets in ${left} h`}
          {user?.demo_days_ahead > 0 && ` · ${user.demo_days_ahead} day${user.demo_days_ahead === 1 ? '' : 's'} ahead`}
        </Typography>
        <Button size="small" startIcon={<FastForward />} onClick={skipAhead} disabled={busy}>
          Skip ahead a day
        </Button>
        <Button size="small" color="inherit" onClick={end} disabled={busy}>End demo</Button>
      </Box>
      {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
    </Box>
  );
};

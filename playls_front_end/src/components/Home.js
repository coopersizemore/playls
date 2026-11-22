import React, { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Badge,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  CircularProgress,
  Container,
  Grid,
  Toolbar,
  Typography,
} from '@mui/material';
import { Add, History, MusicNote, RotateLeft, SyncProblem } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { api, errorMessage } from '../api';
import { Layout, relativeDays } from './Layout';

const Landing = ({ login }) => (
  <Box sx={{ flexGrow: 1 }}>
    <AppBar position="static">
      <Toolbar>
        <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
          PlayLS
        </Typography>
        <Button color="inherit" onClick={login}>
          Login with Spotify
        </Button>
      </Toolbar>
    </AppBar>
    <Container maxWidth="md" sx={{ mt: 8, textAlign: 'center' }}>
      <Typography variant="h2" component="h1" gutterBottom>
        Welcome to PlayLS
      </Typography>
      <Typography variant="h5" color="text.secondary" paragraph>
        Keep your Spotify playlists fresh by rotating songs in and out
      </Typography>
      <Button variant="contained" size="large" onClick={login} sx={{ mt: 4 }}>
        Get Started with Spotify
      </Button>
    </Container>
  </Box>
);

const RotationCard = ({ rotation }) => {
  const due = rotation.due_count;
  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Box display="flex" alignItems="center" mb={2}>
          <Badge badgeContent={due} color="primary" max={999} sx={{ mr: 2 }}>
            <MusicNote color="primary" />
          </Badge>
          <Typography variant="h6" noWrap>{rotation.name}</Typography>
        </Box>
        <Typography color="text.secondary">
          {due > 0 ? `${due} song${due === 1 ? '' : 's'} ready for review` : 'Nothing due right now'}
        </Typography>
        <Typography color="text.secondary" variant="body2">
          {rotation.active_count} songs · every {rotation.interval_days} days
        </Typography>
        {due === 0 && rotation.next_due_at && (
          <Typography color="text.secondary" variant="body2">
            Next song due {relativeDays(rotation.next_due_at)}
          </Typography>
        )}
        {!rotation.sync_ok && (
          <Box display="flex" alignItems="center" mt={1} color="warning.main">
            <SyncProblem fontSize="small" sx={{ mr: 0.5 }} />
            <Typography variant="body2">Couldn't reach Spotify; counts may be out of date</Typography>
          </Box>
        )}
      </CardContent>
      <CardActions>
        <Button
          size="small"
          variant="contained"
          startIcon={<RotateLeft />}
          component={RouterLink}
          to={`/rotation/${rotation.id}/review`}
          disabled={due === 0}
        >
          Review
        </Button>
        <Button size="small" startIcon={<History />} component={RouterLink} to={`/rotation/${rotation.id}/history`}>
          History
        </Button>
      </CardActions>
    </Card>
  );
};

const Home = () => {
  const { user, login } = useAuth();
  const [rotations, setRotations] = useState(null);
  const [error, setError] = useState('');

  const fetchRotations = useCallback(async () => {
    try {
      setRotations(await api.rotations());
      setError('');
    } catch (e) {
      setError(errorMessage(e, 'Failed to load your rotations.'));
      setRotations([]);
    }
  }, []);

  useEffect(() => {
    if (user) fetchRotations();
  }, [user, fetchRotations]);

  if (!user) return <Landing login={login} />;

  const totalDue = (rotations || []).reduce((sum, r) => sum + r.due_count, 0);

  return (
    <Layout>
      <Typography variant="h4" component="h1" gutterBottom>
        Your Rotations
      </Typography>
      {rotations && rotations.length > 0 && (
        <Typography color="text.secondary" sx={{ mb: 3 }}>
          {totalDue > 0 ? `${totalDue} song${totalDue === 1 ? '' : 's'} waiting for review` : "You're all caught up."}
        </Typography>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {rotations === null ? (
        <Box textAlign="center" mt={6}><CircularProgress /></Box>
      ) : (
        <Grid container spacing={3}>
          {rotations.map((rotation) => (
            <Grid key={rotation.id} size={{ xs: 12, sm: 6, md: 4 }}>
              <RotationCard rotation={rotation} />
            </Grid>
          ))}
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <Card sx={{ height: '100%', border: '2px dashed', borderColor: 'primary.main' }}>
              <CardContent>
                <Box display="flex" alignItems="center" mb={2}>
                  <Add color="primary" sx={{ mr: 1 }} />
                  <Typography variant="h6">Create New Rotation</Typography>
                </Box>
                <Typography color="text.secondary">Connect a playlist to start rotating</Typography>
              </CardContent>
              <CardActions>
                <Button size="small" component={RouterLink} to="/rotation">
                  Create
                </Button>
              </CardActions>
            </Card>
          </Grid>
        </Grid>
      )}
    </Layout>
  );
};

export default Home;

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
  Chip,
  CircularProgress,
  Container,
  Grid,
  IconButton,
  ListItemIcon,
  Menu,
  MenuItem,
  Toolbar,
  Typography,
} from '@mui/material';
import { Add, Delete, Edit, History, LibraryAdd, MoreVert, MusicNote, RotateLeft, SyncProblem } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { api, errorMessage } from '../api';
import { Layout, relativeDays } from './Layout';
import {
  CreateRotationDialog,
  DeleteRotationDialog,
  EditRotationDialog,
  formatInterval,
} from './RotationDialogs';

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

const RotationCard = ({ rotation, onEdit, onDelete }) => {
  const [menuAnchor, setMenuAnchor] = useState(null);
  const due = rotation.due_count;
  const ready = rotation.ready_today;
  const closeMenu = () => setMenuAnchor(null);

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Box display="flex" alignItems="center" mb={1.5}>
          <Badge badgeContent={ready} color="primary" max={999} sx={{ mr: 2 }}>
            <MusicNote color="primary" />
          </Badge>
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>{rotation.name}</Typography>
          <IconButton size="small" aria-label={`More options for ${rotation.name}`}
            onClick={(e) => setMenuAnchor(e.currentTarget)}>
            <MoreVert fontSize="small" />
          </IconButton>
        </Box>
        <Typography color="text.secondary">
          {due === 0
            ? 'Nothing due right now'
            : ready > 0
              ? `${ready} song${ready === 1 ? '' : 's'} ready to review today`
              : "Done for today"}
        </Typography>
        {due > ready && (
          <Typography color="text.secondary" variant="body2">
            {due} due in total{rotation.daily_limit ? ` · up to ${rotation.daily_limit} a day` : ''}
          </Typography>
        )}
        {due === 0 && rotation.next_due_at && (
          <Typography color="text.secondary" variant="body2">
            Next song due {relativeDays(rotation.next_due_at)}
          </Typography>
        )}
        <Box display="flex" gap={1} flexWrap="wrap" mt={1.5}>
          <Chip size="small" label={`${rotation.active_count} songs`} />
          <Chip size="small" label={`every ${formatInterval(rotation.interval_hours)}`} />
          {!rotation.grace_period && <Chip size="small" variant="outlined" label="no grace period" />}
        </Box>
        {!rotation.sync_ok && (
          <Box display="flex" alignItems="center" mt={1.5} color="warning.main">
            <SyncProblem fontSize="small" sx={{ mr: 0.5 }} />
            <Typography variant="body2">Couldn't reach Spotify; counts may be out of date</Typography>
          </Box>
        )}
      </CardContent>
      <CardActions>
        <Button size="small" variant="contained" startIcon={<RotateLeft />} component={RouterLink}
          to={`/rotation/${rotation.id}/review`} disabled={due === 0}>
          {due > 0 && ready === 0 ? 'Review more' : 'Review'}
        </Button>
        <Button size="small" startIcon={<LibraryAdd />} component={RouterLink} to={`/rotation/${rotation.id}/restock`}>
          Restock
        </Button>
        <Button size="small" startIcon={<History />} component={RouterLink} to={`/rotation/${rotation.id}/history`}>
          History
        </Button>
      </CardActions>
      <Menu anchorEl={menuAnchor} open={!!menuAnchor} onClose={closeMenu}>
        <MenuItem onClick={() => { closeMenu(); onEdit(rotation); }}>
          <ListItemIcon><Edit fontSize="small" /></ListItemIcon>Edit
        </MenuItem>
        <MenuItem onClick={() => { closeMenu(); onDelete(rotation); }} sx={{ color: 'error.main' }}>
          <ListItemIcon><Delete fontSize="small" color="error" /></ListItemIcon>Delete
        </MenuItem>
      </Menu>
    </Card>
  );
};

const Home = () => {
  const { user, login } = useAuth();
  const [rotations, setRotations] = useState(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const fetchRotations = useCallback(async () => {
    try {
      setRotations(await api.rotations());
      setError('');
    } catch (e) {
      setError(errorMessage(e, 'Failed to load your rotations.'));
      setRotations((current) => current || []);
    }
  }, []);

  useEffect(() => {
    if (user) fetchRotations();
  }, [user, fetchRotations]);

  if (!user) return <Landing login={login} />;

  const totalReady = (rotations || []).reduce((sum, r) => sum + r.ready_today, 0);

  return (
    <Layout>
      <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={2} mb={1}>
        <Typography variant="h4" component="h1">Your Rotations</Typography>
        <Button variant="contained" startIcon={<Add />} onClick={() => setCreating(true)}>
          New Rotation
        </Button>
      </Box>
      {rotations && rotations.length > 0 && (
        <Typography color="text.secondary" sx={{ mb: 3 }}>
          {totalReady > 0 ? `${totalReady} song${totalReady === 1 ? '' : 's'} ready to review today` : "You're all caught up for today."}
        </Typography>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {rotations === null ? (
        <Box textAlign="center" mt={6}><CircularProgress /></Box>
      ) : rotations.length === 0 ? (
        <Card sx={{ mt: 3, border: '2px dashed', borderColor: 'primary.main', textAlign: 'center' }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>No rotations yet</Typography>
            <Typography color="text.secondary" paragraph>
              Wrap a playlist you own and PlayLS will bring each song back up for review on your schedule.
            </Typography>
            <Button variant="contained" startIcon={<Add />} onClick={() => setCreating(true)}>
              Create your first rotation
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Grid container spacing={3}>
          {rotations.map((rotation) => (
            <Grid key={rotation.id} size={{ xs: 12, sm: 6, md: 4 }}>
              <RotationCard rotation={rotation} onEdit={setEditing} onDelete={setDeleting} />
            </Grid>
          ))}
        </Grid>
      )}

      <CreateRotationDialog open={creating} onClose={() => setCreating(false)}
        onCreated={() => { setCreating(false); fetchRotations(); }} />
      <EditRotationDialog rotation={editing} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); fetchRotations(); }} />
      <DeleteRotationDialog rotation={deleting} onClose={() => setDeleting(null)}
        onDeleted={() => { setDeleting(null); fetchRotations(); }} />
    </Layout>
  );
};

export default Home;

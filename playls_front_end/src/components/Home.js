import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert,
  Badge,
  Box,
  Button,
  ButtonBase,
  Card,
  CardActions,
  CardContent,
  Container,
  Grid,
  Typography,
} from '@mui/material';
import { Add, AddCircleOutline, Autorenew, Sync, SyncProblem } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { api, errorMessage } from '../api';
import { Layout, PlaylistCover, relativeDays } from './Layout';
import { CreateRotationDialog, formatInterval } from './RotationDialogs';
import { RotationCardsSkeleton } from './Skeletons';
import { HelpDialog, hasSeenHelp } from './Help';

const Landing = ({ login }) => (
  <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
    <Container maxWidth="sm" sx={{ pt: 10, textAlign: 'center' }}>
      <Typography variant="h3" component="h1" gutterBottom sx={{ fontWeight: 700, letterSpacing: '0.04em' }}>
        PlayLS
      </Typography>
      <Typography variant="h6" color="text.secondary" paragraph>
        A lazy Susan for your playlists. Songs come back around for review, and you decide what stays.
      </Typography>
      <Button variant="contained" size="large" onClick={login} sx={{ mt: 4, px: 4, py: 1.5 }}>
        Log in with Spotify
      </Button>
    </Container>
  </Box>
);

const RotationCard = ({ rotation, syncing }) => {
  const due = rotation.due_count;
  const ready = rotation.ready_today;
  // An auto rotation may rotate out and restock during its sync. Opening it meanwhile would
  // start a second sync that could restock it again, so wait for this one.
  const locked = syncing && rotation.kind === 'auto';

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Tapping the card opens the rotation, like a playlist in Spotify */}
      <ButtonBase component={RouterLink} to={`/rotation/${rotation.id}`} disabled={locked}
        sx={{ display: 'block', textAlign: 'left', flexGrow: 1, borderRadius: 0 }}>
        <CardContent>
          <Box display="flex" alignItems="center" gap={2} mb={1.5}>
            <PlaylistCover rotation={rotation} size={72} radius={2} shadow />
            <Box minWidth={0}>
              <Typography variant="h6" noWrap>{rotation.name}</Typography>
              <Typography variant="body2" color="text.secondary">
                {rotation.kind === 'auto'
                  ? `Auto · ${rotation.active_count}/${rotation.target_size} songs · ${rotation.rotate_percent}% every ${formatInterval(rotation.interval_hours)}`
                  : `${rotation.active_count} songs · every ${formatInterval(rotation.interval_hours)}`}
              </Typography>
            </Box>
          </Box>
          <Typography>
            {rotation.kind === 'auto'
              ? `${due} song${due === 1 ? '' : 's'} rotating out ${relativeDays(rotation.next_rotation_at)}`
              : due === 0
              ? 'Nothing due right now'
              : ready > 0
                ? `${ready} song${ready === 1 ? '' : 's'} ready to review today`
                : 'Done for today'}
          </Typography>
          <Typography color="text.secondary" variant="body2">
            {rotation.kind === 'auto' && 'Reviewing is optional'}
            {rotation.kind !== 'auto' && due === 0 && rotation.next_due_at && `Next song due ${relativeDays(rotation.next_due_at)}`}
            {rotation.kind !== 'auto' && due > ready && `${due} due in total${rotation.daily_limit ? ` · up to ${rotation.daily_limit} a day` : ''}`}
          </Typography>
          {syncing ? (
            <Box display="flex" alignItems="center" mt={1} color="text.secondary">
              <Sync fontSize="small" sx={{ mr: 0.5 }} />
              <Typography variant="body2">Checking Spotify…</Typography>
            </Box>
          ) : !rotation.sync_ok && (
            <Box display="flex" alignItems="center" mt={1} color="warning.main">
              <SyncProblem fontSize="small" sx={{ mr: 0.5 }} />
              <Typography variant="body2">Couldn't reach Spotify; counts may be out of date</Typography>
            </Box>
          )}
        </CardContent>
      </ButtonBase>
      <CardActions sx={{ px: 2, pb: 2, gap: 1 }}>
        <Badge badgeContent={rotation.kind === 'auto' ? 0 : ready} color="error" max={999}>
          <Button variant="contained" startIcon={<Autorenew />} component={RouterLink}
            to={`/rotation/${rotation.id}/review`} disabled={due === 0 || locked}>
            {rotation.kind === 'auto' ? 'Review' : due > 0 && ready === 0 ? 'Rotate more' : 'Rotate'}
          </Button>
        </Badge>
        <Button variant="outlined" color="inherit" startIcon={<AddCircleOutline />} component={RouterLink}
          to={`/rotation/${rotation.id}/restock`} disabled={locked}>
          Restock
        </Button>
      </CardActions>
    </Card>
  );
};

const Home = () => {
  const { user, login } = useAuth();
  const [rotations, setRotations] = useState(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [syncing, setSyncing] = useState(() => new Set()); // rotation ids still checking Spotify
  const generation = useRef(0); // ignores syncs from an earlier load
  const [help, setHelp] = useState(false);

  // Show what's stored right away, then check each rotation against Spotify in parallel
  // (one request each) and update its card when it answers.
  const fetchRotations = useCallback(async () => {
    const gen = ++generation.current;
    let list;
    try {
      list = await api.rotations({ sync: false });
      if (gen !== generation.current) return;
      setRotations(list);
      setError('');
    } catch (e) {
      if (gen !== generation.current) return;
      setError(errorMessage(e, 'Failed to load your rotations.'));
      setRotations((current) => current || []);
      return;
    }
    setSyncing(new Set(list.map((r) => r.id)));
    list.forEach((r) => {
      api.rotation(r.id)
        .catch(() => ({ ...r, sync_ok: false })) // keep the stored numbers, flag them as possibly stale
        .then((fresh) => {
          if (gen !== generation.current) return;
          setRotations((current) => (current || []).map((x) => (x.id === r.id ? fresh : x)));
          setSyncing((current) => { const next = new Set(current); next.delete(r.id); return next; });
        });
    });
  }, []);

  useEffect(() => {
    if (user) fetchRotations();
  }, [user, fetchRotations]);

  // First visit of a new account: no rotations yet and the guide not seen on this device
  const noRotations = rotations !== null && rotations.length === 0;
  useEffect(() => {
    if (user && noRotations && !hasSeenHelp(user.id)) setHelp(true);
  }, [user, noRotations]);

  if (!user) return <Landing login={login} />;

  const totalReady = (rotations || []).reduce((sum, r) => sum + (r.kind === 'auto' ? 0 : r.ready_today), 0);

  return (
    <Layout>
      <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={2} mb={1} mt={1}>
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
        <RotationCardsSkeleton />
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
              <RotationCard rotation={rotation} syncing={syncing.has(rotation.id)} />
            </Grid>
          ))}
        </Grid>
      )}

      <HelpDialog open={help} onClose={() => setHelp(false)} userId={user.id} />
      <CreateRotationDialog open={creating} onClose={() => setCreating(false)}
        onCreated={() => { setCreating(false); fetchRotations(); }} />
    </Layout>
  );
};

export default Home;

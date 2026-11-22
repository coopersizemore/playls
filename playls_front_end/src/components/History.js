import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  CircularProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Snackbar,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import { Check, MusicNote, Replay, Undo } from '@mui/icons-material';
import { api, errorMessage } from '../api';
import { Layout, RotationHeader, formatDate } from './Layout';

const TABS = [
  { label: 'All', filter: () => true },
  { label: 'Removed', filter: (e) => e.action === 'remove' },
  { label: 'Kept', filter: (e) => e.action === 'keep' || e.action === 'super_keep' },
  { label: 'Skipped', filter: (e) => e.action === 'skip' },
];

const ACTION_CHIP = {
  keep: { label: 'Kept', color: 'success' },
  super_keep: { label: 'Super kept', color: 'warning' },
  remove: { label: 'Removed', color: 'error' },
  skip: { label: 'Skipped', color: 'default' },
  undo: { label: 'Undo', color: 'default' },
};

const History = () => {
  const { rotationId } = useParams();
  const [rotation, setRotation] = useState(null);
  const [events, setEvents] = useState(null);
  const [tab, setTab] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(null); // track_id being updated
  // Current status per track after actions taken on this page (overrides the loaded status)
  const [statusOverride, setStatusOverride] = useState({});
  const [toast, setToast] = useState('');

  const load = useCallback(() => {
    Promise.all([api.rotation(rotationId, { sync: false }), api.history(rotationId)])
      .then(([summary, history]) => { setRotation(summary); setEvents(history); setStatusOverride({}); })
      .catch((e) => { setError(errorMessage(e, 'Failed to load history.')); setEvents([]); });
  }, [rotationId]);

  useEffect(() => { load(); }, [load]);

  const statusOf = (track) => statusOverride[track.track_id] || track.status;

  // Removed (already off Spotify) -> add it back to the playlist, as a fresh song
  const addBack = async (track) => {
    setBusy(track.track_id);
    setError('');
    try {
      await api.restockAdd(rotationId, track.track_id, 'bring_back');
      setStatusOverride((s) => ({ ...s, [track.track_id]: 'active' }));
      setToast(`Added “${track.title}” back to the playlist`);
    } catch (e) {
      if (e?.response?.status === 409) setStatusOverride((s) => ({ ...s, [track.track_id]: 'active' }));
      else setError(errorMessage(e, "Couldn't add that song back."));
    } finally {
      setBusy(null);
    }
  };

  // Still pending (not yet removed on Spotify) -> just cancel the removal
  const undoRemoval = async (track) => {
    setBusy(track.track_id);
    setError('');
    try {
      await api.review(rotationId, track.track_id, 'undo');
      setStatusOverride((s) => ({ ...s, [track.track_id]: 'active' }));
      setToast(`Kept “${track.title}” in the playlist`);
    } catch (e) {
      // Most likely the removal reached Spotify in the meantime: reload to offer "Add back"
      setError(errorMessage(e, "Couldn't undo that removal."));
      load();
    } finally {
      setBusy(null);
    }
  };

  const shown = (events || []).filter(TABS[tab].filter);
  // Only the newest event per song gets an action button
  const newestEventKey = new Map();
  (events || []).forEach((e, i) => { if (!newestEventKey.has(e.track.track_id)) newestEventKey.set(e.track.track_id, i); });

  const actionFor = (e, i) => {
    if (newestEventKey.get(e.track.track_id) !== i) return null;
    const status = statusOf(e.track);
    if (status === 'removed') {
      return (
        <Button size="small" variant="outlined" startIcon={<Replay />} disabled={busy === e.track.track_id}
          onClick={() => addBack(e.track)}>Add back</Button>
      );
    }
    if (status === 'pending_removal') {
      return (
        <Button size="small" variant="outlined" startIcon={<Undo />} disabled={busy === e.track.track_id}
          onClick={() => undoRemoval(e.track)}>Undo removal</Button>
      );
    }
    if (e.action === 'remove' && status === 'active') {
      return <Chip size="small" icon={<Check />} label="Back in rotation" />;
    }
    return null;
  };

  return (
    <Layout maxWidth="md">
      <RotationHeader rotation={rotation} title={rotation ? `${rotation.name}: History` : 'History'} />
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {TABS.map((t) => <Tab key={t.label} label={t.label} />)}
      </Tabs>

      {events === null ? (
        <Box textAlign="center" mt={6}><CircularProgress /></Box>
      ) : shown.length === 0 ? (
        <Typography color="text.secondary">No reviews yet.</Typography>
      ) : (
        <List>
          {shown.map((e) => {
            const i = events.indexOf(e);
            const chip = ACTION_CHIP[e.action] || { label: e.action, color: 'default' };
            const action = actionFor(e, i);
            return (
              <ListItem key={`${e.created_at}-${e.track.track_id}-${i}`} divider>
                <ListItemAvatar>
                  <Avatar variant="rounded" src={e.track.image_url || undefined}><MusicNote /></Avatar>
                </ListItemAvatar>
                <ListItemText
                  primary={e.track.title}
                  secondary={`${e.track.artists || ''} · ${formatDate(e.created_at)}`}
                />
                <Box display="flex" alignItems="center" gap={1} flexShrink={0} ml={1} flexWrap="wrap" justifyContent="flex-end">
                  {action}
                  <Chip size="small" label={chip.label} color={chip.color} />
                </Box>
              </ListItem>
            );
          })}
        </List>
      )}

      <Snackbar open={!!toast} autoHideDuration={4000} onClose={() => setToast('')} message={toast} />
    </Layout>
  );
};

export default History;

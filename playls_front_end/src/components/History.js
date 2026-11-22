import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Chip,
  CircularProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import { MusicNote } from '@mui/icons-material';
import { api, errorMessage } from '../api';
import { Layout, formatDate } from './Layout';

const TABS = [
  { label: 'All', filter: () => true },
  { label: 'Removed', filter: (e) => e.action === 'remove' },
  { label: 'Kept', filter: (e) => e.action === 'keep' },
  { label: 'Skipped', filter: (e) => e.action === 'skip' },
];

const ACTION_CHIP = {
  keep: { label: 'Kept', color: 'success' },
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

  useEffect(() => {
    Promise.all([api.rotation(rotationId, { sync: false }), api.history(rotationId)])
      .then(([summary, history]) => { setRotation(summary); setEvents(history); })
      .catch((e) => { setError(errorMessage(e, 'Failed to load history.')); setEvents([]); });
  }, [rotationId]);

  const shown = (events || []).filter(TABS[tab].filter);

  return (
    <Layout maxWidth="md">
      <Typography variant="h4" component="h1" gutterBottom>
        {rotation ? `${rotation.name}: History` : 'History'}
      </Typography>
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
          {shown.map((e, i) => {
            const chip = ACTION_CHIP[e.action] || { label: e.action, color: 'default' };
            return (
              <ListItem key={`${e.created_at}-${e.track.track_id}-${i}`} divider
                secondaryAction={<Chip size="small" label={chip.label} color={chip.color} />}>
                <ListItemAvatar>
                  <Avatar variant="rounded" src={e.track.image_url || undefined}><MusicNote /></Avatar>
                </ListItemAvatar>
                <ListItemText
                  primary={e.track.title}
                  secondary={`${e.track.artists || ''} · ${formatDate(e.created_at)}`}
                />
              </ListItem>
            );
          })}
        </List>
      )}
    </Layout>
  );
};

export default History;

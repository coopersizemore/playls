import React from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Typography,
} from '@mui/material';
import { MusicNote, SkipNext, Star, ThumbDown, ThumbUp } from '@mui/icons-material';
import { formatInterval } from './RotationDialogs';
import { PlaylistCover } from './Layout';

const Section = ({ icon, title, subtitle, tracks }) => (
  <Card sx={{ mb: 2 }}>
    <CardContent>
      <Box display="flex" alignItems="center" gap={1} mb={0.5}>
        {icon}
        <Typography variant="h6">{title}</Typography>
        <Chip size="small" label={tracks.length} />
      </Box>
      <Typography variant="body2" color="text.secondary">{subtitle}</Typography>
      <List dense>
        {tracks.map((t) => (
          <ListItem key={t.track_id} disableGutters>
            <ListItemAvatar>
              <Avatar variant="rounded" src={t.image_url || undefined}><MusicNote /></Avatar>
            </ListItemAvatar>
            <ListItemText primary={t.title} secondary={t.artists} />
          </ListItem>
        ))}
      </List>
    </CardContent>
  </Card>
);

// Shown once, when a review session ends (Done / Stop for now). Lives only in page
// state, so it doesn't come back on reload.
const ReviewSummary = ({ rotationId, rotation, log, flushed }) => {
  // Last action per track wins (e.g. a removal that was undone and then kept)
  const latest = new Map();
  log.forEach((entry) => latest.set(entry.track.track_id, entry));
  const byAction = (action) => [...latest.values()].filter((e) => e.action === action).map((e) => e.track);
  const kept = byAction('keep');
  const superKept = byAction('super_keep');
  const removed = byAction('remove');
  const skipped = byAction('skip');
  const interval = rotation ? formatInterval(rotation.interval_hours) : null;
  const superInterval = rotation ? formatInterval(rotation.interval_hours * (rotation.super_keep_multiplier || 3)) : null;

  return (
    <Box>
      <Box display="flex" justifyContent="center" mb={2}><PlaylistCover rotation={rotation} size={96} /></Box>
      <Typography variant="h4" gutterBottom textAlign="center">Session complete</Typography>
      <Typography color="text.secondary" textAlign="center" paragraph>
        You reviewed {latest.size} song{latest.size === 1 ? '' : 's'}
        {rotation ? ` in ${rotation.name}` : ''}.
      </Typography>

      {removed.length > 0 && !flushed && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Couldn't reach Spotify just now. Removed songs will be taken out of the playlist automatically
          the next time PlayLS syncs.
        </Alert>
      )}

      {removed.length > 0 && (
        <Section
          icon={<ThumbDown color="error" />}
          title="Removed"
          subtitle={flushed ? 'Taken out of your Spotify playlist. You can add them back from History or Restock.'
            : 'Will be taken out of your Spotify playlist shortly.'}
          tracks={removed}
        />
      )}
      {kept.length > 0 && (
        <Section
          icon={<ThumbUp color="success" />}
          title="Kept"
          subtitle={interval ? `Staying in the playlist. They'll come up for review again in ${interval}.` : 'Staying in the playlist.'}
          tracks={kept}
        />
      )}
      {superKept.length > 0 && (
        <Section
          icon={<Star color="warning" />}
          title="Super kept"
          subtitle={superInterval ? `Staying put for longer: back up for review in ${superInterval}.` : 'Staying in the playlist for longer.'}
          tracks={superKept}
        />
      )}
      {skipped.length > 0 && (
        <Section
          icon={<SkipNext />}
          title="Skipped"
          subtitle={`Still in the playlist and still due. They'll come back ${
            (rotation?.skip_hold_days || 1) > 1 ? `in ${rotation.skip_hold_days} days` : 'tomorrow'}.`}
          tracks={skipped}
        />
      )}

      <Box display="flex" justifyContent="center" gap={2} mt={3} flexWrap="wrap">
        <Button variant="contained" component={RouterLink} to={`/rotation/${rotationId}`}>Back to rotation</Button>
        {removed.length > 0 && (
          <Button variant="outlined" component={RouterLink} to={`/rotation/${rotationId}/restock`}>Restock</Button>
        )}
        <Button component={RouterLink} to={`/rotation/${rotationId}?tab=history`}>History</Button>
      </Box>
    </Box>
  );
};

export default ReviewSummary;

import React, { useEffect, useState } from 'react';
import {
  Avatar,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Typography,
} from '@mui/material';
import { MusicNote } from '@mui/icons-material';
import { api } from '../api';
import { relativeDays } from './Layout';
import { PlaysIcon } from './Listening';

const SOURCE_LABELS = {
  bring_back: 'Bring back',
  picks: 'PlayLS picks',
  suggested: 'For you',
  search: 'Search',
  rediscover: 'Rediscover',
};

// "6 of 10 songs added here lately have been played", from listening history. Tapping it shows
// the breakdown by source and each song. Display only: it doesn't change any suggestions.
const RestockOutcomes = ({ rotationId, refreshKey }) => {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.restockOutcomes(rotationId).then(setData).catch(() => setData(null));
  }, [rotationId, refreshKey]);

  if (!data?.enabled || data.added === 0) return null;

  return (
    <>
      <Button size="small" color="inherit" onClick={() => setOpen(true)} startIcon={<PlaysIcon sx={{ fontSize: 16 }} />}
        sx={{ color: 'text.secondary', textTransform: 'none', px: 0.5, py: 0, minHeight: 0 }}>
        {data.played} of {data.added} song{data.added === 1 ? '' : 's'} added here lately {data.played === 1 ? 'has' : 'have'} been played
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>How your adds worked out</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" paragraph>
            Songs added to this rotation in the last {Math.round(data.window_days / 30)} months, and whether
            you've played them since, from your listening history.
          </Typography>
          {data.by_source.map((s) => (
            <Box key={s.source} mb={1.5}>
              <Box display="flex" justifyContent="space-between">
                <Typography variant="body2">{SOURCE_LABELS[s.source] || s.source}</Typography>
                <Typography variant="body2" color="text.secondary">{s.played} of {s.added} played</Typography>
              </Box>
              <LinearProgress variant="determinate" value={s.added ? (100 * s.played) / s.added : 0}
                aria-label={`${SOURCE_LABELS[s.source] || s.source}: ${s.played} of ${s.added} played`}
                sx={{ height: 6, borderRadius: 3, mt: 0.5 }} />
            </Box>
          ))}
          <List dense sx={{ mt: 1 }}>
            {data.songs.map((song) => (
              <ListItem key={song.track_id} disableGutters>
                <ListItemAvatar>
                  <Avatar variant="rounded" src={song.image_url || undefined}><MusicNote /></Avatar>
                </ListItemAvatar>
                <ListItemText sx={{ minWidth: 0 }} primary={song.title}
                  secondary={`${SOURCE_LABELS[song.source] || song.source} · added ${relativeDays(song.added_at)}`
                    + (song.status === 'active' ? '' : ' · no longer in rotation')}
                  slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }} />
                <Typography variant="body2" sx={{ ml: 1, whiteSpace: 'nowrap' }}>
                  {song.plays ? `${song.plays}×` : 'Not yet'}
                </Typography>
              </ListItem>
            ))}
          </List>
        </DialogContent>
        <DialogActions><Button onClick={() => setOpen(false)}>Close</Button></DialogActions>
      </Dialog>
    </>
  );
};

export default RestockOutcomes;

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  LinearProgress,
  Snackbar,
  Typography,
} from '@mui/material';
import { SkipNext, ThumbDown, ThumbUp, Undo } from '@mui/icons-material';
import { api, errorMessage, flushOnExit } from '../api';
import { Layout, formatDate } from './Layout';

// Review a rotation's due songs. Each swipe is saved right away (DB only); removals are
// pushed to Spotify in one batch when leaving the page (and before any later sync).
const Review = () => {
  const { rotationId } = useParams();
  const navigate = useNavigate();
  const [rotation, setRotation] = useState(null);
  const [queue, setQueue] = useState(null);
  const [index, setIndex] = useState(0);
  const [counts, setCounts] = useState({ keep: 0, skip: 0, remove: 0 });
  const [lastRemoved, setLastRemoved] = useState(null); // { track, index }
  const [busy, setBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState('');
  const pendingRemovals = useRef(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // The queue call syncs with Spotify; the summary afterwards doesn't need to again
        const tracks = await api.queue(rotationId);
        const summary = await api.rotation(rotationId, { sync: false });
        if (!cancelled) { setQueue(tracks); setRotation(summary); }
      } catch (e) {
        if (!cancelled) { setError(errorMessage(e, 'Failed to load songs to review.')); setQueue([]); }
      }
    })();
    return () => { cancelled = true; };
  }, [rotationId]);

  // Flush pending removals when the tab is hidden/closed or the user navigates away
  useEffect(() => {
    const flushIfNeeded = () => {
      if (pendingRemovals.current > 0) {
        pendingRemovals.current = 0;
        flushOnExit(rotationId);
      }
    };
    const onVisibility = () => { if (document.visibilityState === 'hidden') flushIfNeeded(); };
    window.addEventListener('pagehide', flushIfNeeded);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('pagehide', flushIfNeeded);
      document.removeEventListener('visibilitychange', onVisibility);
      flushIfNeeded();
    };
  }, [rotationId]);

  const act = useCallback(async (action) => {
    const track = queue?.[index];
    if (!track || busy) return;
    setBusy(true);
    setError('');
    try {
      await api.review(rotationId, track.track_id, action);
      if (action === 'remove') {
        pendingRemovals.current += 1;
        setLastRemoved({ track, index });
      } else {
        setLastRemoved(null);
      }
      setCounts((c) => ({ ...c, [action]: c[action] + 1 }));
      setIndex((i) => i + 1);
    } catch (e) {
      setError(errorMessage(e, "Couldn't save that. Please try again."));
    } finally {
      setBusy(false);
    }
  }, [queue, index, busy, rotationId]);

  const undo = async () => {
    if (!lastRemoved || busy) return;
    setBusy(true);
    try {
      await api.review(rotationId, lastRemoved.track.track_id, 'undo');
      pendingRemovals.current = Math.max(0, pendingRemovals.current - 1);
      setCounts((c) => ({ ...c, remove: c.remove - 1 }));
      setIndex(lastRemoved.index);
      setLastRemoved(null);
    } catch (e) {
      setError(errorMessage(e, "Couldn't undo. The song may already be removed on Spotify."));
      setLastRemoved(null);
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    setFinishing(true);
    try {
      if (pendingRemovals.current > 0) {
        await api.flush(rotationId);
        pendingRemovals.current = 0;
      }
      navigate('/');
    } catch (e) {
      // Removals stay pending server-side and are retried on the next sync
      setError(errorMessage(e, "Couldn't update Spotify yet. Removals will be retried automatically."));
      pendingRemovals.current = 0;
      setFinishing(false);
    }
  };

  // Keyboard shortcuts: ← remove, → keep, ↓ skip
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft') act('remove');
      else if (e.key === 'ArrowRight') act('keep');
      else if (e.key === 'ArrowDown') act('skip');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [act]);

  if (queue === null) {
    return <Layout maxWidth="sm"><Box textAlign="center" mt={8}><CircularProgress /></Box></Layout>;
  }

  const track = queue[index];
  const done = !track;
  const reviewed = Math.min(index, queue.length);

  return (
    <Layout maxWidth="sm">
      <Box textAlign="center" mb={3}>
        <Typography variant="h4" gutterBottom>{rotation?.name || 'Review Songs'}</Typography>
        {queue.length > 0 && (
          <>
            <Typography color="text.secondary">
              {done ? `Reviewed ${queue.length} of ${queue.length}` : `${index + 1} of ${queue.length}`}
            </Typography>
            <LinearProgress variant="determinate" value={(reviewed / queue.length) * 100} sx={{ mt: 1 }} />
          </>
        )}
      </Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {done ? (
        <Box textAlign="center" mt={4}>
          <Typography variant="h5" gutterBottom>
            {queue.length === 0 ? 'Nothing to review' : 'All caught up!'}
          </Typography>
          {queue.length > 0 && (
            <Typography color="text.secondary" paragraph>
              Kept {counts.keep} · Removed {counts.remove} · Skipped {counts.skip}
            </Typography>
          )}
          <Box display="flex" justifyContent="center" gap={2} mt={2}>
            <Button variant="contained" onClick={finish} disabled={finishing}>
              {finishing ? 'Updating Spotify…' : 'Done'}
            </Button>
            <Button component={RouterLink} to={`/rotation/${rotationId}/history`}>History</Button>
          </Box>
        </Box>
      ) : (
        <>
          <Card sx={{ mb: 3 }}>
            <Box
              component="iframe"
              key={track.track_id}
              title={`Spotify player: ${track.title}`}
              src={`https://open.spotify.com/embed/track/${encodeURIComponent(track.track_id)}`}
              allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
              loading="lazy"
              sx={{ width: '100%', height: 152, border: 0, display: 'block' }}
            />
            <CardContent>
              <Typography variant="h5" component="h2" gutterBottom>{track.title}</Typography>
              <Typography color="text.secondary" gutterBottom>{track.artists}</Typography>
              {track.album && <Typography variant="body2" color="text.secondary">{track.album}</Typography>}
              <Box display="flex" gap={1} mt={2} flexWrap="wrap">
                <Chip size="small" label={`Added ${formatDate(track.added_at)}`} />
                {track.last_kept_at && <Chip size="small" label={`Last kept ${formatDate(track.last_kept_at)}`} />}
              </Box>
            </CardContent>
          </Card>

          <Box display="flex" justifyContent="center" gap={2} flexWrap="wrap">
            <Button variant="contained" color="error" size="large" startIcon={<ThumbDown />}
              onClick={() => act('remove')} disabled={busy} sx={{ minWidth: 120 }}>Remove</Button>
            <Button variant="outlined" size="large" startIcon={<SkipNext />}
              onClick={() => act('skip')} disabled={busy} sx={{ minWidth: 120 }}>Skip</Button>
            <Button variant="contained" color="success" size="large" startIcon={<ThumbUp />}
              onClick={() => act('keep')} disabled={busy} sx={{ minWidth: 120 }}>Keep</Button>
          </Box>
          <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mt={2}>
            Keyboard: ← remove · ↓ skip · → keep. Skipped songs come back next time.
          </Typography>
          <Box textAlign="center" mt={3}>
            <Button onClick={finish} disabled={finishing}>
              {finishing ? 'Updating Spotify…' : 'Stop for now'}
            </Button>
          </Box>
        </>
      )}

      <Snackbar
        open={!!lastRemoved}
        onClose={(_, reason) => { if (reason !== 'clickaway') setLastRemoved(null); }}
        autoHideDuration={6000}
        message={lastRemoved ? `Removed “${lastRemoved.track.title}”` : ''}
        action={<Button color="primary" size="small" startIcon={<Undo />} onClick={undo}>Undo</Button>}
      />
    </Layout>
  );
};

export default Review;

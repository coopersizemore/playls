import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// Review a rotation's due songs in daily batches (the user's review limit, most overdue
// first). Each swipe is saved right away (DB only); removals are pushed to Spotify in one
// batch when leaving the page (and before any later sync).
const Review = () => {
  const { rotationId } = useParams();
  const navigate = useNavigate();
  const [rotation, setRotation] = useState(null);
  const [batch, setBatch] = useState(null); // queue response for the current batch
  const [index, setIndex] = useState(0);
  const [counts, setCounts] = useState({ keep: 0, skip: 0, remove: 0 });
  const [lastRemoved, setLastRemoved] = useState(null); // { track, index }
  const [busy, setBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState('');
  const pendingRemovals = useRef(0);

  const loadBatch = useCallback(async (more = false) => {
    setError('');
    try {
      const next = await api.queue(rotationId, { more });
      setBatch(next);
      setIndex(0);
      setLastRemoved(null);
    } catch (e) {
      setError(errorMessage(e, 'Failed to load songs to review.'));
      setBatch((current) => current || {
        tracks: [], due_count: 0, daily_limit: null, reviewed_today: 0, remaining_after_batch: 0, limit_reached: false,
      });
    }
  }, [rotationId]);

  useEffect(() => {
    // The queue call syncs with Spotify; the summary afterwards doesn't need to again
    loadBatch().then(() => api.rotation(rotationId, { sync: false }).then(setRotation).catch(() => {}));
  }, [rotationId, loadBatch]);

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

  const tracks = useMemo(() => batch?.tracks || [], [batch]);

  const act = useCallback(async (action) => {
    const track = tracks[index];
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
  }, [tracks, index, busy, rotationId]);

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

  if (batch === null) {
    return <Layout maxWidth="sm"><Box textAlign="center" mt={8}><CircularProgress /></Box></Layout>;
  }

  const track = tracks[index];
  const done = !track;
  const reviewedInSession = counts.keep + counts.skip + counts.remove;
  // Songs still due after this batch (the server's count is from when the batch was loaded)
  const moreDue = batch.remaining_after_batch;
  const nextBatchSize = batch.daily_limit ? Math.min(batch.daily_limit, moreDue) : moreDue;

  return (
    <Layout maxWidth="sm">
      <Box textAlign="center" mb={3}>
        <Typography variant="h4" gutterBottom>{rotation?.name || 'Review Songs'}</Typography>
        {tracks.length > 0 && (
          <>
            <Typography color="text.secondary">
              {done ? `Reviewed ${tracks.length} of ${tracks.length}` : `${index + 1} of ${tracks.length}`}
              {batch.due_count > tracks.length && ` · ${batch.due_count} due in total`}
            </Typography>
            <LinearProgress variant="determinate" value={(Math.min(index, tracks.length) / tracks.length) * 100} sx={{ mt: 1 }} />
          </>
        )}
      </Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {done ? (
        <Box textAlign="center" mt={4}>
          <Typography variant="h5" gutterBottom>
            {moreDue > 0 ? 'Done for today!' : tracks.length === 0 && reviewedInSession === 0 ? 'Nothing to review' : 'All caught up!'}
          </Typography>
          {reviewedInSession > 0 && (
            <Typography color="text.secondary" paragraph>
              Kept {counts.keep} · Removed {counts.remove} · Skipped {counts.skip}
            </Typography>
          )}
          {moreDue > 0 && (
            <Typography color="text.secondary" paragraph>
              {plural(moreDue, 'more song')} {moreDue === 1 ? 'is' : 'are'} due. The next{' '}
              {batch.daily_limit ? `${Math.min(batch.daily_limit, moreDue)} ` : ''}will be ready tomorrow,
              or you can keep going now.
            </Typography>
          )}
          {moreDue === 0 && batch.due_count > 0 && tracks.length === 0 && (
            <Typography color="text.secondary" paragraph>
              Songs you skipped today will come back tomorrow.
            </Typography>
          )}
          <Box display="flex" justifyContent="center" gap={2} mt={2} flexWrap="wrap">
            <Button variant="contained" onClick={finish} disabled={finishing}>
              {finishing ? 'Updating Spotify…' : 'Done'}
            </Button>
            {moreDue > 0 && (
              <Button variant="outlined" onClick={() => loadBatch(true)} disabled={finishing}>
                Review {nextBatchSize} more
              </Button>
            )}
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
                <Chip size="small" label={track.added_at ? `Added ${formatDate(track.added_at)}` : 'Added date unknown'} />
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
            Keyboard: ← remove · ↓ skip · → keep. Skipped songs come back tomorrow.
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

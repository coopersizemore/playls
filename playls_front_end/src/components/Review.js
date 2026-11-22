import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from 'react-router-dom';
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
import { ArrowBack, ArrowForward, Check, SkipNext, Star, ThumbDown, ThumbUp, Undo } from '@mui/icons-material';
import { formatInterval } from './RotationDialogs';
import { api, errorMessage, flushOnExit } from '../api';
import { Layout, RotationHeader, formatDate } from './Layout';
import ReviewSummary from './ReviewSummary';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

const DECIDED_LABEL = {
  keep: 'You kept this song',
  super_keep: 'You super kept this song',
  remove: 'You removed this song',
  skip: 'You skipped this song',
};

// Review a rotation's due songs in daily batches (the user's review limit, most overdue
// first). Each decision is saved right away (DB only); removals are pushed to Spotify in
// one batch when leaving the page (and before any later sync).
//
// Navigation: Keep / Super keep / Remove decide and move on. Back and Skip/Next move
// through the batch, so earlier songs can be revisited and their decision changed (the old
// decision is undone server-side, then the new one applied). Skip on an undecided song
// records a skip; on a decided song it just moves forward.
const Review = () => {
  const { rotationId } = useParams();
  // ?all=1: review every song in the rotation, not just today's due batch
  const reviewAll = useSearchParams()[0].get('all') === '1';
  const navigate = useNavigate();
  const [rotation, setRotation] = useState(null);
  const [batch, setBatch] = useState(null); // queue response for the current batch
  const [index, setIndex] = useState(0);
  // Current decision per song this session: { [track_id]: { track, action, index, batch, locked } }.
  // `locked`: a removal already pushed to Spotify, which can no longer be changed here.
  const [decisions, setDecisions] = useState({});
  const [toast, setToast] = useState(null); // { track } after a removal, with Undo
  const [summary, setSummary] = useState(null); // { flushed } once the session has ended
  const [busy, setBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState('');
  const pendingRemovals = useRef(0);
  const batchNo = useRef(0);

  const loadBatch = useCallback(async (more = false) => {
    setError('');
    try {
      const next = await api.queue(rotationId, { more, all: reviewAll });
      batchNo.current += 1;
      setBatch(next);
      setIndex(0);
      setToast(null);
    } catch (e) {
      setError(errorMessage(e, 'Failed to load songs to review.'));
      setBatch((current) => current || {
        tracks: [], due_count: 0, daily_limit: null, reviewed_today: 0, remaining_after_batch: 0, limit_reached: false,
      });
    }
  }, [rotationId, reviewAll]);

  useEffect(() => {
    // The queue call syncs with Spotify; the summary afterwards doesn't need to again
    loadBatch().then(() => api.rotation(rotationId, { sync: false }).then(setRotation).catch(() => {}));
  }, [rotationId, loadBatch]);

  // Flush pending removals when the tab is hidden/closed or the user navigates away.
  // Flushed removals are locked: they're off the Spotify playlist now.
  useEffect(() => {
    const flushIfNeeded = () => {
      if (pendingRemovals.current > 0) {
        pendingRemovals.current = 0;
        flushOnExit(rotationId);
        setDecisions((d) => Object.fromEntries(Object.entries(d).map(([id, entry]) => (
          [id, entry.action === 'remove' ? { ...entry, locked: true } : entry]
        ))));
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
  const track = tracks[index];
  const current = track ? decisions[track.track_id] : null;

  const setDecision = (trackId, entry) => setDecisions((d) => {
    const next = { ...d };
    if (entry) next[trackId] = entry; else delete next[trackId];
    return next;
  });

  // Keep / super keep / remove / skip the song on screen, replacing any earlier decision
  const decide = useCallback(async (action) => {
    if (!track || busy || summary) return;
    const prev = decisions[track.track_id];
    if (prev && prev.action === action) {
      setIndex((i) => i + 1); // same decision: just move on
      return;
    }
    if (prev?.locked) {
      setError('That song was already removed from your Spotify playlist. Add it back from History or Restock.');
      return;
    }
    setBusy(true);
    setError('');
    setToast(null);
    try {
      if (prev) {
        await api.review(rotationId, track.track_id, 'undo'); // revert the old decision first
        if (prev.action === 'remove') pendingRemovals.current = Math.max(0, pendingRemovals.current - 1);
        setDecision(track.track_id, null);
      }
      await api.review(rotationId, track.track_id, action);
      if (action === 'remove') {
        pendingRemovals.current += 1;
        setToast({ track });
      }
      setDecision(track.track_id, { track, action, index, batch: batchNo.current, locked: false });
      setIndex((i) => i + 1);
    } catch (e) {
      setError(errorMessage(e, "Couldn't save that. Please try again."));
    } finally {
      setBusy(false);
    }
  }, [track, busy, summary, decisions, rotationId, index]);

  // Skip / Next: records a skip for an undecided song, otherwise just moves forward
  const forward = useCallback(() => {
    if (!track || busy || summary) return;
    if (current) setIndex((i) => i + 1);
    else decide('skip');
  }, [track, busy, summary, current, decide]);

  const back = useCallback(() => {
    if (busy || summary || index === 0) return;
    setError('');
    setIndex((i) => Math.max(0, i - 1));
  }, [busy, summary, index]);

  // The removal toast's Undo: put the song back and return to it
  const undoRemoval = async () => {
    const entry = toast && decisions[toast.track.track_id];
    setToast(null);
    if (!entry || entry.action !== 'remove' || busy) return;
    if (entry.locked) {
      setError('That song was already removed from your Spotify playlist. Add it back from History or Restock.');
      return;
    }
    setBusy(true);
    try {
      await api.review(rotationId, entry.track.track_id, 'undo');
      pendingRemovals.current = Math.max(0, pendingRemovals.current - 1);
      setDecision(entry.track.track_id, null);
      if (entry.batch === batchNo.current) setIndex(entry.index);
    } catch (e) {
      setError(errorMessage(e, "Couldn't undo that removal."));
    } finally {
      setBusy(false);
    }
  };

  // End the session: push removals to Spotify, then show the one-time summary
  const finish = async () => {
    if (Object.keys(decisions).length === 0) {
      navigate('/');
      return;
    }
    setFinishing(true);
    setToast(null);
    let flushed = true;
    try {
      if (pendingRemovals.current > 0) await api.flush(rotationId);
    } catch (e) {
      // Removals stay pending server-side and are retried on the next sync
      flushed = false;
    }
    pendingRemovals.current = 0;
    setSummary({ flushed });
    setFinishing(false);
    window.scrollTo(0, 0);
  };

  // Keyboard: ← remove, → keep, ↑ super keep, ↓ skip / next, Backspace or Z back
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft') decide('remove');
      else if (e.key === 'ArrowRight') decide('keep');
      else if (e.key === 'ArrowUp') { e.preventDefault(); decide('super_keep'); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); forward(); }
      else if (e.key === 'z' || e.key === 'Z' || e.key === 'Backspace') { e.preventDefault(); back(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [decide, forward, back]);

  const decided = Object.values(decisions);
  const counts = decided.reduce((c, d) => ({ ...c, [d.action]: (c[d.action] || 0) + 1 }),
    { keep: 0, super_keep: 0, skip: 0, remove: 0 });

  if (summary) {
    return (
      <Layout maxWidth="sm">
        <ReviewSummary rotationId={rotationId} rotation={rotation} log={decided} flushed={summary.flushed} />
      </Layout>
    );
  }

  if (batch === null) {
    return <Layout maxWidth="sm"><Box textAlign="center" mt={8}><CircularProgress /></Box></Layout>;
  }

  const done = !track;
  const reviewedInSession = decided.length;
  const reviewedInBatch = decided.filter((d) => d.batch === batchNo.current).length;
  // Songs still due after this batch (the server's count is from when the batch was loaded)
  const moreDue = batch.remaining_after_batch;
  const nextBatchSize = batch.daily_limit ? Math.min(batch.daily_limit, moreDue) : moreDue;
  // A decided song shows its decision: that button stays filled, the others go outlined
  const variantFor = (action, filled = 'contained') => (!current || current.action === action ? filled : 'outlined');
  const checkIf = (action, icon) => (current?.action === action ? <Check /> : icon);

  const backButton = (
    <Button startIcon={<ArrowBack />} onClick={back} disabled={busy || index === 0}>Back</Button>
  );

  return (
    <Layout maxWidth="sm">
      <Box textAlign="center" mb={3}>
        <RotationHeader rotation={rotation} title={rotation?.name || 'Review Songs'} centered />
        {reviewAll && (
          <Typography color="text.secondary" variant="body2" mb={0.5}>
            Reviewing every song, soonest due first. Keeping a song pushes its next review out a full interval.
          </Typography>
        )}
        {tracks.length > 0 && (
          <>
            <Typography color="text.secondary">
              {done ? `End of batch` : `Song ${index + 1} of ${tracks.length}`}
              {` · ${reviewedInBatch} reviewed`}
              {batch.due_count > tracks.length && ` · ${batch.due_count} due in total`}
            </Typography>
            <LinearProgress variant="determinate" value={(reviewedInBatch / tracks.length) * 100} sx={{ mt: 1 }} />
          </>
        )}
        {(tracks.length > 0 || reviewedInSession > 0) && (
          // Live tally for the whole session (carries across "Review more" batches)
          <Box display="flex" justifyContent="center" gap={1} mt={1.5} flexWrap="wrap" aria-live="polite">
            <Chip size="small" color="success" variant={counts.keep + counts.super_keep ? 'filled' : 'outlined'}
              icon={<ThumbUp />} label={`${counts.keep + counts.super_keep} kept${counts.super_keep ? ` (${counts.super_keep} super)` : ''}`} />
            <Chip size="small" color="error" variant={counts.remove ? 'filled' : 'outlined'}
              icon={<ThumbDown />} label={`${counts.remove} removed`} />
            <Chip size="small" variant={counts.skip ? 'filled' : 'outlined'}
              icon={<SkipNext />} label={`${counts.skip} skipped`} />
          </Box>
        )}
      </Box>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {done ? (
        <Box textAlign="center" mt={4}>
          <Typography variant="h5" gutterBottom>
            {moreDue > 0 ? 'Done for today!' : tracks.length === 0 && reviewedInSession === 0 ? 'Nothing to review' : 'All caught up!'}
          </Typography>
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
          {tracks.length > 0 && <Box mt={1}>{backButton}</Box>}
          <Box display="flex" justifyContent="center" gap={2} mt={2} flexWrap="wrap">
            <Button variant="contained" onClick={finish} disabled={finishing}>
              {finishing ? 'Updating Spotify…' : 'Done'}
            </Button>
            {moreDue > 0 && (
              <Button variant="outlined" onClick={() => loadBatch(true)} disabled={finishing}>
                Review {nextBatchSize} more
              </Button>
            )}
            {counts.remove > 0 && (
              <Button component={RouterLink} to={`/rotation/${rotationId}/restock`}>Restock</Button>
            )}
            <Button component={RouterLink} to={`/rotation/${rotationId}/history`}>History</Button>
          </Box>
        </Box>
      ) : (
        <>
          <Card sx={{ mb: 3, outline: current ? 2 : 0, outlineColor: 'divider', outlineStyle: 'solid' }}>
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
              {current && (
                <Alert severity={current.action === 'remove' ? 'error' : current.action === 'skip' ? 'info' : 'success'}
                  icon={<Check />} sx={{ mb: 2 }}>
                  {DECIDED_LABEL[current.action]}.{' '}
                  {current.locked ? 'It has already been removed from Spotify.' : 'Choose another action to change it.'}
                </Alert>
              )}
              <Typography variant="h5" component="h2" gutterBottom>{track.title}</Typography>
              <Typography color="text.secondary" gutterBottom>{track.artists}</Typography>
              {track.album && <Typography variant="body2" color="text.secondary">{track.album}</Typography>}
              <Box display="flex" gap={1} mt={2} flexWrap="wrap">
                <Chip size="small" label={track.added_at ? `Added ${formatDate(track.added_at)}` : 'Added date unknown'} />
                {track.is_playable === false && (
                  <Chip size="small" color="warning" label="Unavailable on Spotify" />
                )}
                {reviewAll && track.due_at && new Date(`${track.due_at}Z`) > new Date() && (
                  <Chip size="small" variant="outlined" label={`Not due until ${formatDate(track.due_at)}`} />
                )}
                {track.last_kept_at && !current && (
                  <Chip size="small" icon={track.keep_multiplier > 1 ? <Star /> : undefined}
                    label={`Last ${track.keep_multiplier > 1 ? 'super kept' : 'kept'} ${formatDate(track.last_kept_at)}`} />
                )}
              </Box>
            </CardContent>
          </Card>

          <Box display="flex" justifyContent="center" gap={2} flexWrap="wrap">
            <Button variant={variantFor('remove')} color="error" size="large" startIcon={checkIf('remove', <ThumbDown />)}
              onClick={() => decide('remove')} disabled={busy || current?.locked} sx={{ minWidth: 140 }}>Remove</Button>
            <Button variant={variantFor('keep')} color="success" size="large" startIcon={checkIf('keep', <ThumbUp />)}
              onClick={() => decide('keep')} disabled={busy || current?.locked} sx={{ minWidth: 140 }}>Keep</Button>
          </Box>
          <Box textAlign="center" mt={1.5}>
            <Button variant={current?.action === 'super_keep' ? 'contained' : 'outlined'} color="warning"
              startIcon={checkIf('super_keep', <Star />)} onClick={() => decide('super_keep')}
              disabled={busy || current?.locked} title="Keep, and don't ask again for three times as long">
              Super keep{rotation ? ` · back in ${formatInterval(rotation.interval_hours * 3)}` : ''}
            </Button>
          </Box>

          {/* Back / forward through the batch */}
          <Box display="flex" justifyContent="space-between" alignItems="center" mt={3}>
            {backButton}
            <Button endIcon={current ? <ArrowForward /> : <SkipNext />} onClick={forward} disabled={busy}
              variant={current?.action === 'skip' ? 'contained' : 'text'}>
              {current ? 'Next' : 'Skip'}
            </Button>
          </Box>
          <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mt={1}>
            Keyboard: ← remove · → keep · ↑ super keep · ↓ skip / next · Backspace back.
            Skipped songs come back tomorrow.
          </Typography>
          <Box textAlign="center" mt={3}>
            <Button onClick={finish} disabled={finishing}>
              {finishing ? 'Updating Spotify…' : 'Stop for now'}
            </Button>
          </Box>
        </>
      )}

      <Snackbar
        open={!!toast}
        onClose={(_, reason) => { if (reason !== 'clickaway') setToast(null); }}
        autoHideDuration={6000}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
        message={toast ? `Removed “${toast.track.title}”` : ''}
        action={<Button color="primary" size="small" startIcon={<Undo />} onClick={undoRemoval}>Undo</Button>}
      />
    </Layout>
  );
};

export default Review;

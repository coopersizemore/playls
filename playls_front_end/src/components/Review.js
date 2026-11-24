import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  ButtonBase,
  Chip,
  LinearProgress,
  Snackbar,
  Typography,
  useMediaQuery,
} from '@mui/material';
import {
  ArrowBack,
  ArrowForward,
  Check,
  KeyboardDoubleArrowLeft,
  KeyboardDoubleArrowRight,
  SkipNext,
  Star,
  ThumbDown,
  ThumbUp,
  Undo,
} from '@mui/icons-material';
import { formatInterval } from './RotationDialogs';
import { api, errorMessage, flushOnExit } from '../api';
import { AlbumArt, Layout, SpotifyEmbed, daysSince, parseUtc, relativeDays } from './Layout';
import ReviewSummary from './ReviewSummary';
import { skipReturn, timesWord } from './SettingsControls';
import SwipeCard, { EXIT_MS } from './SwipeCard';
import { ReviewSkeleton } from './Skeletons';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const EXIT_FOR = { keep: 'right', super_keep: 'up', remove: 'left' };

const DECIDED_LABEL = {
  keep: 'You kept this song',
  super_keep: 'You super kept this song',
  remove: 'You removed this song',
  skip: 'You skipped this song',
};

// The big number from the wireframes: days since it was added (or last kept)
const DaysStat = ({ track }) => {
  const kept = !!track.last_kept_at;
  const days = daysSince(kept ? track.last_kept_at : track.added_at);
  return (
    <Box textAlign="center" my={2.5}>
      <Typography sx={{ fontSize: '3.2rem', fontWeight: 700, lineHeight: 1 }}>{days ?? '—'}</Typography>
      <Typography mt={1}>
        {days === null
          ? 'added date unknown'
          : `day${days === 1 ? '' : 's'} since you ${kept ? (track.keep_multiplier > 1 ? 'super kept' : 'last kept') : 'added'} this song`}
      </Typography>
    </Box>
  );
};

// Tappable swipe hint ("« Swipe Left to Remove")
const Hint = ({ side, label, onClick, disabled, active }) => (
  <ButtonBase onClick={onClick} disabled={disabled} sx={{
    flexDirection: 'column', alignItems: side === 'left' ? 'flex-start' : 'flex-end', p: 1, borderRadius: 2,
    textAlign: side, opacity: disabled ? 0.4 : 1, color: active ? (side === 'left' ? 'error.main' : 'success.main') : 'text.primary',
  }}>
    {side === 'left' ? <KeyboardDoubleArrowLeft fontSize="large" /> : <KeyboardDoubleArrowRight fontSize="large" />}
    <Typography variant="body2" sx={{ whiteSpace: 'pre-line', mt: 0.5 }}>{label}</Typography>
  </ButtonBase>
);

// Review a rotation's due songs in daily batches (the user's review limit, most overdue
// first). Each decision is saved right away (DB only); removals are pushed to Spotify in
// one batch when leaving the page (and before any later sync).
//
// Swipe right / → keeps (card flies right), swipe left / ← removes (flies left), ↑ super
// keeps. Back and Skip/Next move through the batch so earlier songs can be revisited and
// their decision changed (the old decision is undone server-side, then the new one applied).
const Review = () => {
  const { rotationId } = useParams();
  // ?all=1: review every song in the rotation, not just today's due batch
  const reviewAll = useSearchParams()[0].get('all') === '1';
  const navigate = useNavigate();
  const touch = useMediaQuery('(pointer: coarse)');
  const [rotation, setRotation] = useState(null);
  const [batch, setBatch] = useState(null); // queue response for the current batch
  const [index, setIndex] = useState(0);
  // Current decision per song this session: { [track_id]: { track, action, index, batch, locked } }.
  // `locked`: a removal already pushed to Spotify, which can no longer be changed here.
  const [decisions, setDecisions] = useState({});
  const [exit, setExit] = useState(null); // card exit animation: 'left' | 'right' | 'up'
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

  const setDecision = useCallback((trackId, entry) => setDecisions((d) => {
    const next = { ...d };
    if (entry) next[trackId] = entry; else delete next[trackId];
    return next;
  }), []);

  // Keep / super keep / remove / skip the song on screen, replacing any earlier decision.
  // The card flies off (right = keep, left = remove, up = super keep) while the API call runs.
  const decide = useCallback(async (action) => {
    if (!track || busy || summary) return;
    const prev = decisions[track.track_id];
    if (prev?.locked && prev.action !== action) {
      setError('That song was already removed from your Spotify playlist. Add it back from History or Restock.');
      return;
    }
    const direction = EXIT_FOR[action] || null;
    setBusy(true);
    setError('');
    setToast(null);
    setExit(direction);
    const animation = sleep(direction ? EXIT_MS : 0);
    try {
      if (!prev || prev.action !== action) {
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
      }
      await animation;
      setIndex((i) => i + 1);
    } catch (e) {
      setError(errorMessage(e, "Couldn't save that. Please try again."));
    } finally {
      setExit(null);
      setBusy(false);
    }
  }, [track, busy, summary, decisions, rotationId, index, setDecision]);

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
      navigate(`/rotation/${rotationId}`);
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
  const backTo = `/rotation/${rotationId}`;

  if (summary) {
    return (
      <Layout maxWidth="sm" back={backTo}>
        <ReviewSummary rotationId={rotationId} rotation={rotation} log={decided} flushed={summary.flushed} />
      </Layout>
    );
  }

  if (batch === null) {
    return <Layout maxWidth="sm" back={backTo}><ReviewSkeleton /></Layout>;
  }

  const done = !track;
  const reviewedInSession = decided.length;
  const reviewedInBatch = decided.filter((d) => d.batch === batchNo.current).length;
  // Songs still due after this batch (the server's count is from when the batch was loaded)
  const moreDue = batch.remaining_after_batch;
  const nextBatchSize = batch.daily_limit ? Math.min(batch.daily_limit, moreDue) : moreDue;
  const locked = !!current?.locked;

  return (
    <Layout maxWidth="sm" back={backTo}>
      {/* Progress + live tally */}
      {tracks.length > 0 && (
        <Box mb={2}>
          <Box display="flex" justifyContent="space-between" alignItems="baseline" gap={1}>
            <Typography variant="body2" noWrap>{rotation?.name}</Typography>
            <Typography variant="body2" color="text.secondary" noWrap>
              {done ? 'End of batch' : `${index + 1} / ${tracks.length}`}
              {batch.due_count > tracks.length && ` · ${batch.due_count} due`}
            </Typography>
          </Box>
          <LinearProgress variant="determinate" value={(reviewedInBatch / tracks.length) * 100}
            sx={{ mt: 1, height: 6, borderRadius: 3 }} />
          <Box display="flex" justifyContent="center" gap={1} mt={1.5} flexWrap="wrap" aria-live="polite">
            <Chip size="small" color="success" variant={counts.keep + counts.super_keep ? 'filled' : 'outlined'}
              icon={<ThumbUp />} label={`${counts.keep + counts.super_keep} kept${counts.super_keep ? ` (${counts.super_keep} super)` : ''}`} />
            <Chip size="small" color="error" variant={counts.remove ? 'filled' : 'outlined'}
              icon={<ThumbDown />} label={`${counts.remove} removed`} />
            <Chip size="small" variant={counts.skip ? 'filled' : 'outlined'}
              icon={<SkipNext />} label={`${counts.skip} skipped`} />
          </Box>
          {reviewAll && (
            <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mt={1}>
              Reviewing every song, soonest due first.
            </Typography>
          )}
        </Box>
      )}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}

      {done ? (
        <Box textAlign="center" mt={6}>
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
              Songs you skipped will come back {skipReturn(rotation?.skip_hold_days || 1)}.
            </Typography>
          )}
          {tracks.length > 0 && (
            <Button startIcon={<ArrowBack />} onClick={back} disabled={busy} sx={{ mt: 1 }}>Back to the last song</Button>
          )}
          <Box display="flex" justifyContent="center" gap={2} mt={2} flexWrap="wrap">
            <Button variant="contained" onClick={finish} disabled={finishing}>
              {finishing ? 'Updating Spotify…' : 'Done'}
            </Button>
            {moreDue > 0 && (
              <Button variant="outlined" color="inherit" onClick={() => loadBatch(true)} disabled={finishing}>
                Review {nextBatchSize} more
              </Button>
            )}
            {counts.remove > 0 && (
              <Button component={RouterLink} to={`/rotation/${rotationId}/restock`}>Restock</Button>
            )}
          </Box>
        </Box>
      ) : (
        <>
          <Box sx={{ px: { xs: 2, sm: 5 } }}>
            <SwipeCard key={track.track_id} exit={exit} disabled={busy || locked}
              onSwipe={(dir) => decide(dir === 'right' ? 'keep' : 'remove')}>
              <AlbumArt src={track.image_url} alt={track.album || track.title} />
              {current && (
                <Chip
                  icon={<Check />}
                  color={current.action === 'remove' ? 'error' : current.action === 'skip' ? 'default' : 'success'}
                  label={`${DECIDED_LABEL[current.action]}${locked ? ' · already removed from Spotify' : ''}`}
                  sx={{ position: 'absolute', left: '50%', bottom: 12, transform: 'translateX(-50%)', maxWidth: '92%' }}
                />
              )}
            </SwipeCard>
          </Box>

          <Box textAlign="center" mt={3}>
            <Typography variant="h5" component="h2" sx={{ overflowWrap: 'anywhere' }}>{track.title}</Typography>
            <Typography mt={1}>{track.artists}</Typography>
            <Box display="flex" justifyContent="center" gap={1} mt={1} flexWrap="wrap">
              {track.is_playable === false && <Chip size="small" color="warning" label="Unavailable on Spotify" />}
              {rotation?.kind === 'auto' ? (
                track.protected
                  ? <Chip size="small" variant="outlined" label="Kept for the next rotation" />
                  : track.due_at && <Chip size="small" variant="outlined" label={`Leaves ${relativeDays(track.due_at)}`} />
              ) : reviewAll && track.due_at && parseUtc(track.due_at) > new Date() && (
                <Chip size="small" variant="outlined" label="Not due yet" />
              )}
            </Box>
          </Box>

          <DaysStat track={track} />

          <SpotifyEmbed trackId={track.track_id} title={track.title} compact />

          <Box display="flex" justifyContent="space-between" alignItems="flex-end" mt={3}>
            <Hint side="left" label={touch ? 'Swipe Left\nto Remove' : 'Remove\n(← key)'}
              onClick={() => decide('remove')} disabled={busy || locked} active={current?.action === 'remove'} />
            <Button variant={current?.action === 'super_keep' ? 'contained' : 'outlined'} color="warning"
              startIcon={current?.action === 'super_keep' ? <Check /> : <Star />} onClick={() => decide('super_keep')}
              disabled={busy || locked}
              title={`Keep, and don't ask again for ${timesWord(rotation?.super_keep_multiplier || 3)} as long`} sx={{ mb: 1 }}>
              Super keep
            </Button>
            <Hint side="right" label={touch ? 'Swipe Right\nto Keep' : 'Keep\n(→ key)'}
              onClick={() => decide('keep')} disabled={busy || locked} active={current?.action === 'keep'} />
          </Box>
          {rotation && (
            <Typography variant="caption" color="text.secondary" display="block" textAlign="center">
              {rotation.kind === 'auto'
                ? `Kept songs stay through the next rotation; super kept songs age ${timesWord(rotation.super_keep_multiplier)} slower. Removed songs are replaced.`
                : <>Kept songs come back in {formatInterval(rotation.interval_hours)}, super kept in{' '}
                  {formatInterval(rotation.interval_hours * rotation.super_keep_multiplier)}.</>}
            </Typography>
          )}

          {/* Back / forward through the batch */}
          <Box display="flex" justifyContent="space-between" alignItems="center" mt={2}>
            <Button startIcon={<ArrowBack />} onClick={back} disabled={busy || index === 0} color="inherit">Back</Button>
            <Button onClick={finish} disabled={finishing} color="inherit" size="small">
              {finishing ? 'Updating Spotify…' : 'Stop for now'}
            </Button>
            <Button endIcon={current ? <ArrowForward /> : <SkipNext />} onClick={forward} disabled={busy} color="inherit"
              variant={current?.action === 'skip' ? 'outlined' : 'text'}>
              {current ? 'Next' : 'Skip'}
            </Button>
          </Box>
          {!touch && (
            <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mt={1}>
              Drag the card, or use ← remove · → keep · ↑ super keep · ↓ skip · Backspace back
            </Typography>
          )}
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

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  Collapse,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Pagination,
  Snackbar,
  Typography,
} from '@mui/material';
import { Check, ExpandLess, ExpandMore, MusicNote, Replay, Undo } from '@mui/icons-material';
import { api, errorMessage } from '../api';
import { parseUtc } from './Layout';
import { ListSkeleton } from './Skeletons';
import { PlaysIcon, hoursLabel } from './Listening';

// Each tab is filtered on the server, so older events of one kind aren't hidden behind newer ones
const TABS = [
  { label: 'All', filter: 'all' },
  { label: 'Removed', filter: 'removed' },
  { label: 'Kept', filter: 'kept' },
  { label: 'Skipped', filter: 'skipped' },
  { label: 'Rotated', filter: 'rotated', autoOnly: true },
  { label: 'Listening', filter: 'listening', listening: true },
];
const PAGE_SIZE = 25;

// Events this close together count as one review session (sessions aren't stored)
const SESSION_GAP_MS = 30 * 60 * 1000;

const ACTION_CHIP = {
  keep: { label: 'Kept', color: 'success' },
  super_keep: { label: 'Super kept', color: 'warning' },
  remove: { label: 'Removed', color: 'error' },
  skip: { label: 'Skipped', color: 'default' },
  undo: { label: 'Undo', color: 'default' },
  rotated_out: { label: 'Rotated out', color: 'info' },
  auto_added: { label: 'Added', color: 'primary' },
};

const dayLabel = (date) => {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    ...(date.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}),
  });
};

const timeLabel = (date) => date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });

// "Today · 9:27 PM – 9:41 PM" for one session (its events are newest first)
const sessionLabel = (events) => {
  const oldest = parseUtc(events[events.length - 1].created_at);
  const newest = parseUtc(events[0].created_at);
  const start = timeLabel(oldest);
  const end = timeLabel(newest);
  return `${dayLabel(oldest)} · ${start === end ? start : `${start} – ${end}`}`;
};

// "12 plays in the 4 weeks before · played 3× since" for kept and removed songs
const playsNote = (e) => {
  if (e.plays_before == null) return null;
  const before = `${e.plays_before} play${e.plays_before === 1 ? '' : 's'} in the ${hoursLabel(e.plays_window_hours)} before`;
  return e.plays_since ? `${before} · played ${e.plays_since}× since` : before;
};

const localDate = (iso) => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
};

// One day of listening: totals, and the songs played (tap to expand)
const ListeningDay = ({ day }) => {
  const [open, setOpen] = useState(false);
  return (
    <Box component="section" mt={1.5}>
      <Button fullWidth color="inherit" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        endIcon={open ? <ExpandLess /> : <ExpandMore />}
        sx={{ justifyContent: 'space-between', textTransform: 'none', px: 2, py: 1 }}>
        <Box textAlign="left" minWidth={0}>
          <Typography variant="subtitle2" component="h3">{dayLabel(localDate(day.date))}</Typography>
          <Typography variant="body2" color="text.secondary">
            <PlaysIcon sx={{ fontSize: 14, mr: 0.5, verticalAlign: '-2px' }} />
            {day.plays_here} from this playlist
            {day.plays_elsewhere > 0 && ` · ${day.plays_elsewhere} of its songs elsewhere`}
          </Typography>
        </Box>
      </Button>
      <Collapse in={open} unmountOnExit>
        <List dense disablePadding>
          {day.songs.map((song) => (
            <ListItem key={song.track_id}>
              <ListItemAvatar>
                <Avatar variant="rounded" src={song.image_url || undefined}><MusicNote /></Avatar>
              </ListItemAvatar>
              <ListItemText sx={{ minWidth: 0 }} primary={song.title} secondary={song.artists || ' '}
                slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }} />
              <Typography variant="body2" sx={{ ml: 1, whiteSpace: 'nowrap' }}>
                {song.plays}×{song.plays_here && song.plays_here !== song.plays ? ` (${song.plays_here} here)` : ''}
              </Typography>
            </ListItem>
          ))}
        </List>
      </Collapse>
    </Box>
  );
};

// The Listening tab: a month of daily play digests
const ListeningDigest = ({ rotationId }) => {
  const [digest, setDigest] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.listeningDigest(rotationId, { days: 30 }).then(setDigest)
      .catch((e) => { setError(errorMessage(e, 'Failed to load listening.')); setDigest({ days: [] }); });
  }, [rotationId]);
  if (digest === null) return <ListSkeleton count={4} />;
  return (
    <>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {digest.days.length === 0 ? (
        <Typography color="text.secondary" py={2}>
          {digest.since
            ? 'No plays of these songs in the last 30 days.'
            : 'Nothing yet. Your plays show up here as PlayLS saves them (Settings → Listening).'}
        </Typography>
      ) : digest.days.map((day) => <ListeningDay key={day.date} day={day} />)}
      {digest.since && (
        <Typography variant="caption" color="text.secondary" display="block" mt={2} px={2}>
          Plays PlayLS has saved since {parseUtc(digest.since).toLocaleDateString()}. Spotify only shares recent
          plays, so some may be missing.
        </Typography>
      )}
    </>
  );
};

// Split a newest-first page into sessions: a new one starts after a long enough gap
const toSessions = (events) => {
  const sessions = [];
  events.forEach((event, index) => {
    const prev = events[index - 1];
    const gap = prev ? parseUtc(prev.created_at) - parseUtc(event.created_at) : Infinity;
    if (gap > SESSION_GAP_MS) sessions.push([]);
    sessions[sessions.length - 1].push({ event, index });
  });
  return sessions;
};

// A rotation's review history with Add back / Undo removal actions, in pages of 25 and
// grouped by review session. Embedded in the rotation page's History tab. `onChanged` lets
// the page refresh its counts; `auto` shows the Rotated tab (auto rotations' rotate-outs and additions).
export const HistoryList = ({ rotationId, onChanged, auto = false }) => {
  const [events, setEvents] = useState(null);
  const [tab, setTab] = useState(0);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const request = useRef(0); // ignores responses for a page or tab that's no longer shown
  const top = useRef(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(null); // track_id being updated
  // Current status per track after actions taken on this page (overrides the loaded status)
  const [statusOverride, setStatusOverride] = useState({});
  const [toast, setToast] = useState('');

  const filter = TABS[tab].filter;
  const listeningTab = !!TABS[tab].listening;

  const load = useCallback(() => {
    if (listeningTab) return;
    const id = ++request.current;
    setEvents(null);
    api.historyPage(rotationId, { filter, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
      .then((result) => {
        if (id !== request.current) return;
        setEvents(result.events);
        setTotal(result.total);
        setStatusOverride({});
      })
      .catch((e) => {
        if (id !== request.current) return;
        setError(errorMessage(e, 'Failed to load history.'));
        setEvents([]);
        setTotal(0);
      });
  }, [rotationId, filter, page, listeningTab]);

  useEffect(() => { load(); }, [load]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const changeTab = (i) => { setTab(i); setPage(1); };
  const changePage = (_, p) => {
    setPage(p);
    top.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const statusOf = (track) => statusOverride[track.track_id] || track.status;

  // Removed (already off Spotify) -> add it back to the playlist, as a fresh song
  const addBack = async (track) => {
    setBusy(track.track_id);
    setError('');
    try {
      await api.restockAdd(rotationId, track.track_id, 'bring_back');
      setStatusOverride((s) => ({ ...s, [track.track_id]: 'active' }));
      setToast(`Added “${track.title}” back to the playlist`);
      onChanged?.();
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
      onChanged?.();
    } catch (e) {
      // Most likely the removal reached Spotify in the meantime: reload to offer "Add back"
      setError(errorMessage(e, "Couldn't undo that removal."));
      load();
    } finally {
      setBusy(null);
    }
  };

  // Only the newest event per song on this page gets an action button
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
    if ((e.action === 'remove' || e.action === 'rotated_out') && status === 'active') {
      return <Chip size="small" icon={<Check />} label="Back in rotation" />;
    }
    return null;
  };

  return (
    <Box ref={top} sx={{ scrollMarginTop: 16 }}>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Box display="flex" gap={1} flexWrap="wrap" mb={1}>
        {TABS.map((t, i) => (t.autoOnly && !auto) ? null : (
          <Chip key={t.label} label={t.label} onClick={() => changeTab(i)}
            color={tab === i ? 'primary' : 'default'} variant={tab === i ? 'filled' : 'outlined'} />
        ))}
      </Box>

      {listeningTab ? (
        <ListeningDigest rotationId={rotationId} />
      ) : events === null ? (
        <ListSkeleton count={6} />
      ) : events.length === 0 ? (
        <Typography color="text.secondary" py={2}>Nothing here yet.</Typography>
      ) : (
        toSessions(events).map((session, s) => (
          <Box key={`${session[0].event.created_at}-${s}`} component="section" mt={s ? 2.5 : 1.5}>
            {/* A quiet caption that starts each review session */}
            <Typography variant="caption" color="text.secondary" component="h3" sx={{ display: 'block', px: 2 }}>
              {sessionLabel(session.map((x) => x.event))}
            </Typography>
            <List disablePadding>
              {session.map(({ event: e, index: i }, j) => {
                const chip = ACTION_CHIP[e.action] || { label: e.action, color: 'default' };
                const action = actionFor(e, i);
                return (
                  <ListItem key={`${e.created_at}-${e.track.track_id}-${i}`} divider={j < session.length - 1}>
                    <ListItemAvatar>
                      <Avatar variant="rounded" src={e.track.image_url || undefined}><MusicNote /></Avatar>
                    </ListItemAvatar>
                    {/* minWidth 0 lets long titles shorten with an ellipsis instead of overflowing */}
                    <ListItemText
                      sx={{ minWidth: 0 }}
                      primary={e.track.title}
                      secondary={(
                        <>
                          <Box component="span" display="block"
                            sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {e.track.artists || ' '}
                          </Box>
                          {playsNote(e) && (
                            <Box component="span" display="block" sx={{ fontSize: '0.75rem' }}>
                              <PlaysIcon sx={{ fontSize: 12, mr: 0.5, verticalAlign: '-1px' }} />{playsNote(e)}
                            </Box>
                          )}
                        </>
                      )}
                      slotProps={{ primary: { noWrap: true, title: e.track.title } }}
                    />
                    <Box display="flex" alignItems="center" gap={1} flexShrink={0} ml={1} flexWrap="wrap"
                      justifyContent="flex-end">
                      {action}
                      <Chip size="small" label={chip.label} color={chip.color} />
                    </Box>
                  </ListItem>
                );
              })}
            </List>
          </Box>
        ))
      )}

      {!listeningTab && events !== null && pages > 1 && (
        <Box display="flex" justifyContent="center" mt={2}>
          <Pagination count={pages} page={page} onChange={changePage} size="small" siblingCount={0} />
        </Box>
      )}

      <Snackbar open={!!toast} autoHideDuration={4000} onClose={() => setToast('')} message={toast} />
    </Box>
  );
};

// Old /rotation/:id/history links open the rotation page's History tab
const History = () => {
  const { rotationId } = useParams();
  return <Navigate to={`/rotation/${rotationId}?tab=history`} replace />;
};

export default History;

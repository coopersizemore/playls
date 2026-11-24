import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  IconButton,
  InputAdornment,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Snackbar,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import {
  Add,
  ArrowBack,
  ArrowForward,
  Block,
  Check,
  Close,
  MusicNote,
  Refresh,
  Search as SearchIcon,
  SkipNext,
  Undo,
} from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { startSession } from '../telemetry';
import { api, errorMessage } from '../api';
import { AlbumArt, Layout, RotationHeader, SpotifyEmbed } from './Layout';
import SwipeCard, { EXIT_MS } from './SwipeCard';
import { ListSkeleton, SongCardSkeleton } from './Skeletons';

const TABS = [
  { source: 'bring_back', label: 'Bring back', empty: 'Nothing to bring back yet. Songs you remove from this rotation show up here, weighted more strongly the longer they have been gone.' },
  { source: 'picks', label: 'PlayLS picks', empty: 'No new PlayLS picks right now. Check back soon.' },
  { source: 'suggested', label: 'For you', empty: 'No suggestions right now. Try refreshing, or listen a little more and check back.' },
  { source: 'search', label: 'Search' },
];

// What each decision looks like on a revisited card
const DECIDED = {
  add: { label: 'Added to the playlist', color: 'success' },
  skip: { label: 'Not now', color: 'default' },
  block: { label: "Won't suggest again", color: 'default' },
};
const EXIT_FOR = { add: 'right', skip: 'left', block: 'left' };

// One card at a time with a player; Add (→) or Not now (←). Like Review, Back and Skip/Next
// move through the deck, picking a different answer for a card undoes the old one first, and
// an add can be undone from the toast (the song is taken back out of the playlist).
const Deck = ({ rotationId, source, emptyText, onAdded }) => {
  const { login } = useAuth();
  const [deck, setDeck] = useState(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [decisions, setDecisions] = useState({}); // { [track_id]: 'add' | 'skip' | 'block' } this session
  const [error, setError] = useState('');
  const [toast, setToast] = useState(null); // { track, action, index } after an add or block, with Undo
  const [exit, setExit] = useState(null); // card animation: right = add, left = not now / block
  const session = useRef(null); // usage telemetry for this deck visit (only sent with consent)
  const furthest = useRef(0);

  useEffect(() => {
    session.current = startSession('restock', rotationId, source);
    const left = () => session.current?.end('left');
    window.addEventListener('pagehide', left);
    return () => { window.removeEventListener('pagehide', left); left(); };
  }, [rotationId, source]);

  const load = useCallback(async (refresh = false) => {
    setDeck(null);
    setError('');
    try {
      setDeck(await api.restockDeck(rotationId, source, { refresh }));
      setIndex(0);
      setDecisions({});
      furthest.current = 0;
    } catch (e) {
      setError(errorMessage(e, 'Failed to load suggestions.'));
      setDeck({ items: [], missing_scopes: [] });
    }
  }, [rotationId, source]);

  useEffect(() => { load(); }, [load]);

  const items = deck?.items || [];
  const current = items[index];
  const decided = current ? decisions[current.track_id] : null;
  const added = Object.values(decisions).filter((a) => a === 'add').length;
  const cardKey = current?.track_id;

  useEffect(() => {
    if (cardKey) {
      furthest.current = Math.max(furthest.current, index);
      session.current?.cardShown();
    } else if (items.length > 0) {
      session.current?.end('exhausted'); // reached the end of the deck
    }
  }, [cardKey, index, items.length]);

  const setDecision = useCallback((trackId, action) => setDecisions((d) => {
    const next = { ...d };
    if (action) next[trackId] = action; else delete next[trackId];
    return next;
  }), []);

  // Take back one decision (server-side), keeping the session's add count in step
  const revert = useCallback(async (track, action, telemetry) => {
    if (action === 'block') await api.unblockSong(track.track_id);
    else await api.restockUndo(rotationId, track.track_id, source, telemetry);
    setDecision(track.track_id, null);
    if (action === 'add') onAdded(-1);
  }, [rotationId, source, setDecision, onAdded]);

  // input ('swipe' | 'button' | 'key') is for usage telemetry only
  const act = useCallback(async (action, input = 'button') => {
    if (!current || busy) return;
    const prev = decisions[current.track_id];
    const telemetry = session.current?.decision({ input, revisit: !!prev || index < furthest.current, position: index });
    setBusy(true);
    setError('');
    setToast(null);
    setExit(EXIT_FOR[action]);
    const animation = new Promise((r) => setTimeout(r, EXIT_MS));
    try {
      if (prev !== action) {
        if (prev) await revert(current, prev);
        if (action === 'add') await api.restockAdd(rotationId, current.track_id, source, telemetry);
        else if (action === 'block') await api.restockBlock(rotationId, current.track_id, source, telemetry);
        else await api.restockSkip(rotationId, current.track_id, source, telemetry);
        setDecision(current.track_id, action);
        if (action === 'add') onAdded(1);
        if (action !== 'skip') setToast({ track: current, action, index });
      }
      await animation;
      setIndex((i) => i + 1);
    } catch (e) {
      if (action === 'add' && e?.response?.status === 409 && !prev) setIndex((i) => i + 1); // already in the rotation
      else setError(errorMessage(e, "Couldn't save that. Please try again."));
    } finally {
      setExit(null);
      setBusy(false);
    }
  }, [current, busy, decisions, index, rotationId, source, revert, setDecision, onAdded]);

  // Skip / Next: move on without answering (nothing is recorded), or past an answered card
  const forward = useCallback(() => {
    if (!current || busy) return;
    setError('');
    setIndex((i) => i + 1);
  }, [current, busy]);

  const back = useCallback(() => {
    if (busy || index === 0) return;
    setError('');
    setIndex((i) => Math.max(0, i - 1));
  }, [busy, index]);

  // The toast's Undo: take the add (or block) back and return to that card
  const undoToast = async () => {
    const entry = toast;
    setToast(null);
    if (!entry || busy || decisions[entry.track.track_id] !== entry.action) return;
    setBusy(true);
    try {
      const telemetry = session.current?.decision({ input: 'button', revisit: true, position: entry.index });
      await revert(entry.track, entry.action, telemetry);
      setIndex(entry.index);
    } catch (e) {
      setError(errorMessage(e, entry.action === 'block'
        ? "Couldn't undo. You can resume it from Settings."
        : "Couldn't undo that add."));
    } finally {
      setBusy(false);
    }
  };

  // Keyboard: → add, ← not now, ↓ skip / next, Backspace or Z back
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowRight') act('add', 'key');
      else if (e.key === 'ArrowLeft') act('skip', 'key');
      else if (e.key === 'ArrowDown') { e.preventDefault(); forward(); }
      else if (e.key === 'z' || e.key === 'Z' || e.key === 'Backspace') { e.preventDefault(); back(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [act, forward, back]);

  if (deck === null) return <SongCardSkeleton stat={false} />;

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
      {deck.missing_scopes?.length > 0 && (
        <Alert severity="info" sx={{ mb: 2 }}
          action={<Button color="inherit" size="small" onClick={login}>Reconnect</Button>}>
          Reconnect Spotify so PlayLS can use your top tracks, recently played and Liked Songs.
        </Alert>
      )}

      {!current ? (
        <Box textAlign="center" mt={4}>
          <Typography variant="h6" gutterBottom>
            {items.length > 0 ? `That's everything for now${added ? `: added ${added}` : ''}` : 'Nothing here'}
          </Typography>
          <Typography color="text.secondary" paragraph>
            {items.length === 0 && (deck.already_in_rotation > 0
              ? `${deck.already_in_rotation} current PlayLS pick${deck.already_in_rotation === 1 ? ' is' : 's are'} already in this rotation, so there's nothing new to add.`
              : emptyText)}
          </Typography>
          {items.length > 0 && (
            <Box mb={1}>
              <Button startIcon={<ArrowBack />} onClick={back} disabled={busy}>Back to the last song</Button>
            </Box>
          )}
          <Button startIcon={<Refresh />} onClick={() => load(source === 'suggested')}>Refresh</Button>
        </Box>
      ) : (
        <>
          <Typography color="text.secondary" textAlign="center" mb={1}>
            {index + 1} of {items.length}{added ? ` · added ${added}` : ''}
          </Typography>
          <Box sx={{ px: { xs: 3, sm: 7 } }}>
            <SwipeCard key={current.track_id} exit={exit} disabled={busy}
              onSwipe={(dir) => act(dir === 'right' ? 'add' : 'skip', 'swipe')}>
              <AlbumArt src={current.image_url} alt={current.album || current.title} />
              {decided && (
                <Chip icon={<Check />} color={DECIDED[decided].color} label={DECIDED[decided].label}
                  sx={{ position: 'absolute', left: '50%', bottom: 12, transform: 'translateX(-50%)', maxWidth: '92%' }} />
              )}
            </SwipeCard>
          </Box>
          <Box textAlign="center" mt={2.5} mb={2}>
            <Typography variant="h5" component="h2" sx={{ overflowWrap: 'anywhere' }}>{current.title}</Typography>
            <Typography mt={0.5}>{current.artists}</Typography>
            {current.reason && <Chip size="small" label={current.reason} sx={{ mt: 1.5 }} />}
          </Box>
          <Box mb={2.5}><SpotifyEmbed trackId={current.track_id} title={current.title} compact /></Box>
          <Box display="flex" justifyContent="center" gap={2}>
            <Button variant={decided === 'skip' ? 'contained' : 'outlined'} color={decided === 'skip' ? 'inherit' : 'primary'}
              size="large" startIcon={<Close />} onClick={() => act('skip')} disabled={busy} sx={{ minWidth: 140 }}>
              Not now
            </Button>
            <Button variant="contained" size="large" startIcon={decided === 'add' ? <Check /> : <Add />}
              onClick={() => act('add')} disabled={busy} sx={{ minWidth: 140 }}>
              {decided === 'add' ? 'Added' : 'Add'}
            </Button>
          </Box>
          {source === 'bring_back' && (
            <Box textAlign="center" mt={1.5}>
              <Button color="inherit" size="small" startIcon={<Block />} onClick={() => act('block')}
                disabled={busy || decided === 'block'} sx={{ color: 'text.secondary' }}>
                Stop suggesting this song
              </Button>
            </Box>
          )}

          {/* Back / forward through the deck */}
          <Box display="flex" justifyContent="space-between" alignItems="center" mt={2}>
            <Button startIcon={<ArrowBack />} onClick={back} disabled={busy || index === 0} color="inherit">Back</Button>
            <Button endIcon={decided ? <ArrowForward /> : <SkipNext />} onClick={forward} disabled={busy} color="inherit">
              {decided ? 'Next' : 'Skip'}
            </Button>
          </Box>
          <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mt={1}>
            Swipe or drag: left = not now, right = add (or ← / → keys; ↓ skip, Backspace back). Adding puts the
            song in your Spotify playlist right away; Skip moves on without answering.
          </Typography>
        </>
      )}
      <Snackbar
        open={!!toast}
        onClose={(_, reason) => { if (reason !== 'clickaway') setToast(null); }}
        autoHideDuration={6000}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
        message={toast ? (toast.action === 'add'
          ? `Added “${toast.track.title}”`
          : `Won't suggest “${toast.track.title}” again`) : ''}
        action={<Button color="primary" size="small" startIcon={<Undo />} onClick={undoToast}>Undo</Button>}
      />
    </Box>
  );
};

// List view: search the Spotify catalog and add tracks
const SearchView = ({ rotationId, onAdded }) => {
  const [query, setQuery] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [results, setResults] = useState([]);
  const [nextOffset, setNextOffset] = useState(null);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(null);
  const [added, setAdded] = useState(new Set());
  const [error, setError] = useState('');

  const run = async (q, offset = 0) => {
    if (!q.trim()) return;
    setLoading(true);
    setError('');
    try {
      const page = await api.restockSearch(rotationId, q.trim(), offset);
      setResults((r) => (offset === 0 ? page.items : [...r, ...page.items]));
      setNextOffset(page.next_offset);
      setSubmitted(q.trim());
    } catch (e) {
      setError(errorMessage(e, 'Search failed.'));
    } finally {
      setLoading(false);
    }
  };

  const add = async (track) => {
    setAdding(track.track_id);
    setError('');
    try {
      await api.restockAdd(rotationId, track.track_id, 'search');
      setAdded((s) => new Set(s).add(track.track_id));
      onAdded();
    } catch (e) {
      if (e?.response?.status === 409) setAdded((s) => new Set(s).add(track.track_id));
      else setError(errorMessage(e, "Couldn't add that song."));
    } finally {
      setAdding(null);
    }
  };

  return (
    <Box>
      <Box component="form" onSubmit={(e) => { e.preventDefault(); run(query); }} mb={2}>
        <TextField
          fullWidth
          autoFocus
          placeholder="Search songs, artists, albums"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          InputProps={{
            endAdornment: (
              <InputAdornment position="end">
                <IconButton type="submit" aria-label="Search" disabled={loading}><SearchIcon /></IconButton>
              </InputAdornment>
            ),
          }}
        />
      </Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {submitted && results.length === 0 && !loading && (
        <Typography color="text.secondary">No songs found for “{submitted}”.</Typography>
      )}
      <List>
        {results.map((t) => {
          const inRotation = t.in_rotation || added.has(t.track_id);
          return (
            <ListItem key={t.track_id} divider secondaryAction={
              inRotation ? (
                <Chip size="small" icon={<Check />} label="In rotation" />
              ) : (
                <Button size="small" variant="outlined" startIcon={<Add />} onClick={() => add(t)}
                  disabled={adding === t.track_id}>Add</Button>
              )
            }>
              <ListItemAvatar>
                <Avatar variant="rounded" src={t.image_url || undefined}><MusicNote /></Avatar>
              </ListItemAvatar>
              <ListItemText primary={t.title} secondary={[t.artists, t.album].filter(Boolean).join(' · ')}
                sx={{ pr: 12 }} />
            </ListItem>
          );
        })}
      </List>
      {loading && <ListSkeleton count={results.length ? 3 : 6} />}
      {nextOffset !== null && !loading && results.length > 0 && (
        <Box textAlign="center" mt={1}>
          <Button onClick={() => run(submitted, nextOffset)}>Load more</Button>
        </Box>
      )}
    </Box>
  );
};

const Restock = () => {
  const { rotationId } = useParams();
  const [rotation, setRotation] = useState(null);
  const [tab, setTab] = useState(0);
  const [addedTotal, setAddedTotal] = useState(0);
  // delta: +1 per add, -1 when an add is undone
  const onAdded = useCallback((delta = 1) => setAddedTotal((n) => Math.max(0, n + delta)), []);

  useEffect(() => {
    api.rotation(rotationId, { sync: false }).then(setRotation).catch(() => {});
  }, [rotationId]);

  const current = TABS[tab];

  return (
    <Layout maxWidth="sm" back={`/rotation/${rotationId}`}>
      <RotationHeader rotation={rotation} title={`Restock${rotation ? `: ${rotation.name}` : ''}`} />
      <Typography color="text.secondary" mb={2}>
        {addedTotal > 0
          ? `Added ${addedTotal} song${addedTotal === 1 ? '' : 's'} this session.`
          : 'Find songs to add to this rotation.'}
        {rotation?.is_liked && ' Adding a song likes it in Spotify.'}
      </Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile sx={{ mb: 3 }}>
        {TABS.map((t) => <Tab key={t.source} label={t.label} />)}
      </Tabs>
      {/* Mounting only the active tab keeps keyboard shortcuts scoped to it */}
      {current.source === 'search' ? (
        <SearchView rotationId={rotationId} onAdded={onAdded} />
      ) : (
        <Deck key={current.source} rotationId={rotationId} source={current.source}
          emptyText={current.empty} onAdded={onAdded} />
      )}
    </Layout>
  );
};

export default Restock;

import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
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
import { Add, Block, Check, Close, MusicNote, Refresh, Search as SearchIcon } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { api, errorMessage } from '../api';
import { Layout, RotationHeader, SpotifyEmbed } from './Layout';

const TABS = [
  { source: 'bring_back', label: 'Bring back', empty: 'Nothing to bring back yet. Songs you remove from this rotation show up here, weighted more strongly the longer they have been gone.' },
  { source: 'picks', label: 'PlayLS picks', empty: 'No new PlayLS picks right now. Check back soon.' },
  { source: 'suggested', label: 'For you', empty: 'No suggestions right now. Try refreshing, or listen a little more and check back.' },
  { source: 'search', label: 'Search' },
];

// One card at a time with a player; Add (→) or Not now (←)
const Deck = ({ rotationId, source, emptyText, onAdded }) => {
  const { login } = useAuth();
  const [deck, setDeck] = useState(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState(0);
  const [error, setError] = useState('');
  const [blocked, setBlocked] = useState(null); // { track, index } for the Undo toast

  const load = useCallback(async (refresh = false) => {
    setDeck(null);
    setError('');
    try {
      setDeck(await api.restockDeck(rotationId, source, { refresh }));
      setIndex(0);
    } catch (e) {
      setError(errorMessage(e, 'Failed to load suggestions.'));
      setDeck({ items: [], missing_scopes: [] });
    }
  }, [rotationId, source]);

  useEffect(() => { load(); }, [load]);

  const items = deck?.items || [];
  const current = items[index];

  const act = useCallback(async (action) => {
    if (!current || busy) return;
    setBusy(true);
    setError('');
    try {
      if (action === 'add') {
        await api.restockAdd(rotationId, current.track_id, source);
        setAdded((n) => n + 1);
        onAdded();
        setBlocked(null);
      } else if (action === 'block') {
        await api.restockBlock(rotationId, current.track_id, source);
        setBlocked({ track: current, index });
      } else {
        await api.restockSkip(rotationId, current.track_id, source);
        setBlocked(null);
      }
      setIndex((i) => i + 1);
    } catch (e) {
      if (e?.response?.status === 409) setIndex((i) => i + 1); // already in the rotation
      else setError(errorMessage(e, "Couldn't save that. Please try again."));
    } finally {
      setBusy(false);
    }
  }, [current, busy, index, rotationId, source, onAdded]);

  const undoBlock = async () => {
    if (!blocked) return;
    try {
      await api.unblockSong(blocked.track.track_id);
      setIndex(blocked.index); // show the card again
    } catch (e) {
      setError(errorMessage(e, "Couldn't undo. You can resume it from Settings."));
    } finally {
      setBlocked(null);
    }
  };

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowRight') act('add');
      else if (e.key === 'ArrowLeft') act('skip');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [act]);

  if (deck === null) return <Box textAlign="center" mt={6}><CircularProgress /></Box>;

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
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
          <Button startIcon={<Refresh />} onClick={() => load(source === 'suggested')}>Refresh</Button>
        </Box>
      ) : (
        <>
          <Typography color="text.secondary" textAlign="center" mb={1}>
            {index + 1} of {items.length}{added ? ` · added ${added}` : ''}
          </Typography>
          <Card sx={{ mb: 3 }}>
            <SpotifyEmbed trackId={current.track_id} title={current.title} />
            <CardContent>
              <Typography variant="h5" component="h2" gutterBottom>{current.title}</Typography>
              <Typography color="text.secondary" gutterBottom>{current.artists}</Typography>
              {current.album && <Typography variant="body2" color="text.secondary">{current.album}</Typography>}
              {current.reason && <Chip size="small" label={current.reason} sx={{ mt: 2 }} />}
            </CardContent>
          </Card>
          <Box display="flex" justifyContent="center" gap={2}>
            <Button variant="outlined" size="large" startIcon={<Close />} onClick={() => act('skip')}
              disabled={busy} sx={{ minWidth: 140 }}>Not now</Button>
            <Button variant="contained" size="large" startIcon={<Add />} onClick={() => act('add')}
              disabled={busy} sx={{ minWidth: 140 }}>Add</Button>
          </Box>
          {source === 'bring_back' && (
            <Box textAlign="center" mt={1.5}>
              <Button color="inherit" size="small" startIcon={<Block />} onClick={() => act('block')} disabled={busy}
                sx={{ color: 'text.secondary' }}>
                Stop suggesting this song
              </Button>
            </Box>
          )}
          <Typography variant="caption" color="text.secondary" display="block" textAlign="center" mt={2}>
            Keyboard: ← not now · → add. Adding puts the song in your Spotify playlist right away.
          </Typography>
        </>
      )}
      <Snackbar
        open={!!blocked}
        onClose={(_, reason) => { if (reason !== 'clickaway') setBlocked(null); }}
        autoHideDuration={6000}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
        message={blocked ? `Won't suggest “${blocked.track.title}” again` : ''}
        action={<Button color="primary" size="small" onClick={undoBlock}>Undo</Button>}
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
      {loading && <Box textAlign="center" my={2}><CircularProgress size={28} /></Box>}
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
  const onAdded = useCallback(() => setAddedTotal((n) => n + 1), []);

  useEffect(() => {
    api.rotation(rotationId, { sync: false }).then(setRotation).catch(() => {});
  }, [rotationId]);

  const current = TABS[tab];

  return (
    <Layout maxWidth="sm">
      <RotationHeader rotation={rotation} title={`Restock${rotation ? `: ${rotation.name}` : ''}`} />
      <Typography color="text.secondary" mb={2}>
        {addedTotal > 0
          ? `Added ${addedTotal} song${addedTotal === 1 ? '' : 's'} this session.`
          : 'Find songs to add to this rotation.'}
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

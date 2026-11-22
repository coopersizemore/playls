import React, { useCallback, useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
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
  ListItemButton,
  ListItemText,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { Delete, MusicNote, Search as SearchIcon } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { api, errorMessage } from '../api';
import { Layout, formatDate } from './Layout';

// <input type="date"> value -> ISO at local midnight (the API stores UTC)
const dateToIso = (value) => (value ? new Date(`${value}T00:00:00`).toISOString() : null);

const artistsOf = (t) => (t.artists || []).map((a) => a.name).join(', ');

const AdminPicks = () => {
  const { user } = useAuth();
  const [picks, setPicks] = useState(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [note, setNote] = useState('');
  const [startsOn, setStartsOn] = useState('');
  const [endsOn, setEndsOn] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const loadPicks = useCallback(() => {
    api.picks().then(setPicks).catch((e) => { setError(errorMessage(e, 'Failed to load picks.')); setPicks([]); });
  }, []);
  useEffect(() => { if (user?.is_admin) loadPicks(); }, [user, loadPicks]);

  if (!user?.is_admin) return <Navigate to="/" replace />;

  const search = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setError('');
    try {
      const res = await api.searchSpotify(query.trim());
      setResults((res.tracks?.items || []).filter((t) => t && t.id));
    } catch (err) {
      setError(errorMessage(err, 'Search failed.'));
    }
  };

  const create = async () => {
    setSaving(true);
    setError('');
    try {
      await api.createPick({
        track_id: selected.id,
        note: note.trim() || null,
        starts_at: dateToIso(startsOn),
        ends_at: dateToIso(endsOn),
      });
      setSelected(null); setNote(''); setStartsOn(''); setEndsOn(''); setResults([]); setQuery('');
      loadPicks();
    } catch (err) {
      setError(errorMessage(err, 'Failed to add the pick.'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (pick) => {
    try {
      await api.deletePick(pick.id);
      loadPicks();
    } catch (err) {
      setError(errorMessage(err, 'Failed to remove the pick.'));
    }
  };

  return (
    <Layout maxWidth="md">
      <Typography variant="h4" component="h1" gutterBottom>Curate PlayLS picks</Typography>
      <Typography color="text.secondary" paragraph>
        Picks show up for every user under Restock → PlayLS picks while they're active.
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Card sx={{ mb: 4 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>Add a pick</Typography>
          {selected ? (
            <>
              <Box display="flex" alignItems="center" gap={2} mb={2}>
                <Avatar variant="rounded" src={selected.album?.images?.[0]?.url}><MusicNote /></Avatar>
                <Box flexGrow={1}>
                  <Typography>{selected.name}</Typography>
                  <Typography variant="body2" color="text.secondary">{artistsOf(selected)}</Typography>
                </Box>
                <Button onClick={() => setSelected(null)}>Change</Button>
              </Box>
              <TextField fullWidth label="Note (optional)" placeholder="Pick of the week" value={note}
                onChange={(e) => setNote(e.target.value)} inputProps={{ maxLength: 300 }} sx={{ mb: 2 }} />
              <Stack direction="row" spacing={2} mb={2}>
                <TextField type="date" label="Starts (optional)" value={startsOn}
                  onChange={(e) => setStartsOn(e.target.value)} InputLabelProps={{ shrink: true }} />
                <TextField type="date" label="Ends (optional)" value={endsOn}
                  onChange={(e) => setEndsOn(e.target.value)} InputLabelProps={{ shrink: true }} />
              </Stack>
              <Button variant="contained" onClick={create} disabled={saving}>
                {saving ? 'Adding…' : 'Add pick'}
              </Button>
            </>
          ) : (
            <>
              <Box component="form" onSubmit={search}>
                <TextField fullWidth placeholder="Search Spotify for a song" value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton type="submit" aria-label="Search"><SearchIcon /></IconButton>
                      </InputAdornment>
                    ),
                  }} />
              </Box>
              <List dense>
                {results.map((t) => (
                  <ListItemButton key={t.id} onClick={() => setSelected(t)}>
                    <ListItemAvatar>
                      <Avatar variant="rounded" src={t.album?.images?.[0]?.url}><MusicNote /></Avatar>
                    </ListItemAvatar>
                    <ListItemText primary={t.name} secondary={`${artistsOf(t)} · ${t.album?.name || ''}`} />
                  </ListItemButton>
                ))}
              </List>
            </>
          )}
        </CardContent>
      </Card>

      <Typography variant="h6" gutterBottom>Current picks</Typography>
      {picks === null ? (
        <Box textAlign="center" mt={3}><CircularProgress /></Box>
      ) : picks.length === 0 ? (
        <Typography color="text.secondary">No picks yet.</Typography>
      ) : (
        <List>
          {picks.map((p) => (
            <ListItem key={p.id} divider secondaryAction={
              <IconButton edge="end" aria-label={`Remove ${p.title}`} onClick={() => remove(p)}><Delete /></IconButton>
            }>
              <ListItemAvatar>
                <Avatar variant="rounded" src={p.image_url || undefined}><MusicNote /></Avatar>
              </ListItemAvatar>
              <ListItemText
                primary={<Box display="flex" alignItems="center" gap={1}>{p.title}
                  <Chip size="small" label={p.active ? 'Active' : 'Inactive'} color={p.active ? 'success' : 'default'} />
                </Box>}
                secondary={[
                  p.artists,
                  p.note,
                  p.starts_at || p.ends_at
                    ? `${p.starts_at ? formatDate(p.starts_at) : '…'} – ${p.ends_at ? formatDate(p.ends_at) : '…'}`
                    : null,
                ].filter(Boolean).join(' · ')}
              />
            </ListItem>
          ))}
        </List>
      )}
    </Layout>
  );
};

export default AdminPicks;

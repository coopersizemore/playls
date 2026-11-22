import React, { useCallback, useEffect, useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  List,
  ListItemAvatar,
  ListItemButton,
  ListItemText,
  MenuItem,
  Radio,
  RadioGroup,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import { Add, CreateNewFolder, Delete, Edit, LibraryMusic, MusicNote } from '@mui/icons-material';
import { api, errorMessage } from '../api';
import { Layout } from './Layout';

const INTERVALS = [7, 14, 30, 60, 90];

const IntervalSelect = ({ value, onChange }) => (
  <FormControl fullWidth sx={{ mt: 2 }}>
    <InputLabel id="interval-label">Review songs every</InputLabel>
    <Select labelId="interval-label" label="Review songs every" value={value} onChange={(e) => onChange(e.target.value)}>
      {(INTERVALS.includes(value) ? INTERVALS : [...INTERVALS, value].sort((a, b) => a - b)).map((d) => (
        <MenuItem key={d} value={d}>{d} days</MenuItem>
      ))}
    </Select>
  </FormControl>
);

const CreateDialog = ({ open, onClose, playlists, onCreated }) => {
  const [mode, setMode] = useState('existing');
  const [playlistId, setPlaylistId] = useState(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [intervalDays, setIntervalDays] = useState(30);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setMode('existing'); setPlaylistId(null); setName(''); setDescription('');
      setIntervalDays(30); setError('');
    }
  }, [open]);

  const available = (playlists || []).filter((p) => p.rotatable && !p.rotation_id);
  const canCreate = mode === 'existing' ? !!playlistId : name.trim() !== '';

  const create = async () => {
    setSaving(true);
    setError('');
    try {
      const body = mode === 'existing'
        ? { playlist_id: playlistId, interval_days: intervalDays }
        : { name: name.trim(), description: description.trim() || null, interval_days: intervalDays };
      await api.createRotation(body);
      onCreated();
    } catch (e) {
      setError(errorMessage(e, 'Failed to create the rotation.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create New Rotation</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <RadioGroup row value={mode} onChange={(e) => setMode(e.target.value)} sx={{ mb: 2 }}>
          <FormControlLabel value="existing" control={<Radio />} label={<Box display="flex" alignItems="center"><LibraryMusic sx={{ mr: 1 }} />Existing playlist</Box>} />
          <FormControlLabel value="scratch" control={<Radio />} label={<Box display="flex" alignItems="center"><CreateNewFolder sx={{ mr: 1 }} />New playlist</Box>} />
        </RadioGroup>

        {mode === 'existing' ? (
          playlists === null ? (
            <Box textAlign="center" my={3}><CircularProgress size={28} /></Box>
          ) : available.length === 0 ? (
            <Typography color="text.secondary">
              No playlists available. You can rotate playlists you own or collaborate on that don't already have a rotation.
            </Typography>
          ) : (
            <List sx={{ maxHeight: 320, overflow: 'auto' }} dense>
              {available.map((p) => (
                <ListItemButton key={p.id} selected={playlistId === p.id} onClick={() => setPlaylistId(p.id)}>
                  <ListItemAvatar>
                    <Avatar variant="rounded" src={p.image_url || undefined}><MusicNote /></Avatar>
                  </ListItemAvatar>
                  <ListItemText primary={p.name} secondary={p.total_items != null ? `${p.total_items} songs` : null} />
                </ListItemButton>
              ))}
            </List>
          )
        ) : (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Creates a new private, empty Spotify playlist. Add songs to it in Spotify and PlayLS picks them up.
            </Typography>
            <TextField fullWidth label="Playlist name" value={name} onChange={(e) => setName(e.target.value)}
              inputProps={{ maxLength: 100 }} sx={{ mb: 2 }} required />
            <TextField fullWidth label="Description (optional)" value={description}
              onChange={(e) => setDescription(e.target.value)} inputProps={{ maxLength: 300 }} multiline rows={2} />
          </>
        )}

        <IntervalSelect value={intervalDays} onChange={setIntervalDays} />
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          Each song comes up for review this many days after it was added. Songs already in the playlist
          first come up this many days from today.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>Cancel</Button>
        <Button variant="contained" onClick={create} disabled={saving || !canCreate}>
          {saving ? 'Creating…' : 'Create Rotation'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

const EditDialog = ({ rotation, onClose, onSaved }) => {
  const [name, setName] = useState('');
  const [intervalDays, setIntervalDays] = useState(30);
  const [error, setError] = useState('');

  useEffect(() => {
    if (rotation) { setName(rotation.name); setIntervalDays(rotation.interval_days); setError(''); }
  }, [rotation]);

  const save = async () => {
    try {
      await api.updateRotation(rotation.id, { name: name.trim(), interval_days: intervalDays });
      onSaved();
    } catch (e) {
      setError(errorMessage(e, 'Failed to save changes.'));
    }
  };

  return (
    <Dialog open={!!rotation} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Edit Rotation</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <TextField fullWidth label="Name" value={name} onChange={(e) => setName(e.target.value)}
          inputProps={{ maxLength: 100 }} sx={{ mt: 1 }} />
        <IntervalSelect value={intervalDays} onChange={setIntervalDays} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!name.trim()}>Save</Button>
      </DialogActions>
    </Dialog>
  );
};

const Rotation = () => {
  const navigate = useNavigate();
  const [rotations, setRotations] = useState(null);
  const [playlists, setPlaylists] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    const [rotationsResult, playlistsResult] = await Promise.allSettled([api.rotations(), api.playlists()]);
    if (rotationsResult.status === 'fulfilled') setRotations(rotationsResult.value);
    else { setRotations([]); setError(errorMessage(rotationsResult.reason, 'Failed to load rotations.')); }
    if (playlistsResult.status === 'fulfilled') setPlaylists(playlistsResult.value);
    else { setPlaylists([]); setError(errorMessage(playlistsResult.reason, 'Failed to load your Spotify playlists.')); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const confirmDelete = async () => {
    try {
      await api.deleteRotation(deleting.id);
      setDeleting(null);
      load();
    } catch (e) {
      setError(errorMessage(e, 'Failed to delete the rotation.'));
      setDeleting(null);
    }
  };

  return (
    <Layout maxWidth="md">
      <Box display="flex" alignItems="center" justifyContent="space-between" mb={3} flexWrap="wrap" gap={2}>
        <Typography variant="h4" component="h1">Manage Rotations</Typography>
        <Button variant="contained" startIcon={<Add />} onClick={() => setCreateOpen(true)}>
          Create New Rotation
        </Button>
      </Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {rotations === null ? (
        <Box textAlign="center" mt={6}><CircularProgress /></Box>
      ) : rotations.length === 0 ? (
        <Typography color="text.secondary">No rotations yet. Create one from a playlist you own.</Typography>
      ) : (
        rotations.map((r) => (
          <Card key={r.id} sx={{ mb: 2 }}>
            <CardContent>
              <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                <MusicNote color="primary" />
                <Typography variant="h6">{r.name}</Typography>
                <Chip size="small" label={`${r.active_count} songs`} />
                <Chip size="small" label={`every ${r.interval_days} days`} />
                {r.due_count > 0 && <Chip size="small" color="primary" label={`${r.due_count} due`} />}
              </Box>
              {r.description && <Typography color="text.secondary" variant="body2" mt={1}>{r.description}</Typography>}
            </CardContent>
            <CardActions>
              <Button size="small" variant="contained" disabled={r.due_count === 0}
                onClick={() => navigate(`/rotation/${r.id}/review`)}>Review</Button>
              <Button size="small" component={RouterLink} to={`/rotation/${r.id}/history`}>History</Button>
              <Button size="small" startIcon={<Edit />} onClick={() => setEditing(r)}>Edit</Button>
              <Button size="small" color="error" startIcon={<Delete />} onClick={() => setDeleting(r)}>Delete</Button>
            </CardActions>
          </Card>
        ))
      )}

      <CreateDialog open={createOpen} onClose={() => setCreateOpen(false)} playlists={playlists}
        onCreated={() => { setCreateOpen(false); load(); }} />
      <EditDialog rotation={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      <Dialog open={!!deleting} onClose={() => setDeleting(null)}>
        <DialogTitle>Delete “{deleting?.name}”?</DialogTitle>
        <DialogContent>
          <Typography>
            This deletes the rotation and its review history from PlayLS. Your Spotify playlist is not changed.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleting(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={confirmDelete}>Delete</Button>
        </DialogActions>
      </Dialog>
    </Layout>
  );
};

export default Rotation;

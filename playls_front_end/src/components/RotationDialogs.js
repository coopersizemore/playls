import React, { useEffect, useState } from 'react';
import {
  Alert,
  Avatar,
  Box,
  Button,
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
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { CreateNewFolder, LibraryMusic, MusicNote } from '@mui/icons-material';
import { api, errorMessage } from '../api';

// ---------- interval (stored in hours) ----------

const MAX_HOURS = 365 * 24;
const UNITS = [
  { key: 'hours', hours: 1 },
  { key: 'days', hours: 24 },
  { key: 'weeks', hours: 24 * 7 },
];
const PRESETS = [
  { label: 'Daily', hours: 24 },
  { label: 'Weekly', hours: 24 * 7 },
  { label: '2 weeks', hours: 24 * 14 },
  { label: '30 days', hours: 24 * 30 },
  { label: '60 days', hours: 24 * 60 },
  { label: '90 days', hours: 24 * 90 },
];

const splitHours = (hours) => {
  if (hours % (24 * 7) === 0) return { amount: hours / (24 * 7), unit: 'weeks' };
  if (hours % 24 === 0) return { amount: hours / 24, unit: 'days' };
  return { amount: hours, unit: 'hours' };
};

export const formatInterval = (hours) => {
  const { amount, unit } = splitHours(hours);
  return `${amount} ${amount === 1 ? unit.slice(0, -1) : unit}`;
};

// Calls onChange(hours) when the input is valid, onChange(null) while it isn't
export const IntervalPicker = ({ value, onChange }) => {
  const initial = splitHours(value || 24 * 30);
  const [amount, setAmount] = useState(String(initial.amount));
  const [unit, setUnit] = useState(initial.unit);

  const emit = (nextAmount, nextUnit) => {
    const n = Number(nextAmount);
    const hours = n * UNITS.find((u) => u.key === nextUnit).hours;
    onChange(Number.isInteger(n) && n >= 1 && hours <= MAX_HOURS ? hours : null);
  };

  const pick = (hours) => {
    const split = splitHours(hours);
    setAmount(String(split.amount));
    setUnit(split.unit);
    onChange(hours);
  };

  const n = Number(amount);
  const invalid = !(Number.isInteger(n) && n >= 1) ||
    n * UNITS.find((u) => u.key === unit).hours > MAX_HOURS;

  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="subtitle2" gutterBottom>Review each song every</Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
        {PRESETS.map((p) => (
          <Chip key={p.hours} label={p.label} onClick={() => pick(p.hours)}
            color={value === p.hours ? 'primary' : 'default'} variant={value === p.hours ? 'filled' : 'outlined'} />
        ))}
      </Stack>
      <Stack direction="row" spacing={1}>
        <TextField
          label="Amount"
          type="number"
          value={amount}
          onChange={(e) => { setAmount(e.target.value); emit(e.target.value, unit); }}
          inputProps={{ min: 1, step: 1 }}
          error={invalid}
          helperText={invalid ? 'Between 1 hour and 365 days' : ' '}
          sx={{ width: 140 }}
        />
        <FormControl sx={{ minWidth: 120 }}>
          <InputLabel id="interval-unit">Unit</InputLabel>
          <Select labelId="interval-unit" label="Unit" value={unit}
            onChange={(e) => { setUnit(e.target.value); emit(amount, e.target.value); }}>
            {UNITS.map((u) => <MenuItem key={u.key} value={u.key}>{u.key}</MenuItem>)}
          </Select>
        </FormControl>
      </Stack>
    </Box>
  );
};

// ---------- grace period ----------

export const GracePeriodSwitch = ({ checked, onChange }) => (
  <Box sx={{ mt: 1 }}>
    <FormControlLabel
      control={<Switch checked={checked} onChange={(e) => onChange(e.target.checked)} />}
      label="Grace period for songs already in the playlist"
    />
    <Typography variant="body2" color="text.secondary">
      {checked
        ? 'On: songs already in the playlist first come up one interval from now.'
        : "Off: songs come up one interval after they were added to the playlist, so older songs may be due right away. Songs whose add date Spotify doesn't know are due immediately."}
    </Typography>
  </Box>
);

// ---------- create ----------

export const CreateRotationDialog = ({ open, onClose, onCreated }) => {
  const [playlists, setPlaylists] = useState(null);
  const [mode, setMode] = useState('existing');
  const [playlistId, setPlaylistId] = useState(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [intervalHours, setIntervalHours] = useState(24 * 30);
  const [grace, setGrace] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setMode('existing'); setPlaylistId(null); setName(''); setDescription('');
    setIntervalHours(24 * 30); setGrace(true); setError(''); setPlaylists(null);
    // Loaded on open so Home doesn't page through every playlist on each visit
    api.playlists()
      .then(setPlaylists)
      .catch((e) => { setPlaylists([]); setError(errorMessage(e, 'Failed to load your Spotify playlists.')); });
  }, [open]);

  const available = (playlists || []).filter((p) => p.rotatable && !p.rotation_id);
  const canCreate = intervalHours !== null && (mode === 'existing' ? !!playlistId : name.trim() !== '');

  const create = async () => {
    setSaving(true);
    setError('');
    try {
      const body = mode === 'existing'
        ? { playlist_id: playlistId, interval_hours: intervalHours, grace_period: grace }
        : { name: name.trim(), description: description.trim() || null, interval_hours: intervalHours };
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
          <FormControlLabel value="existing" control={<Radio />}
            label={<Box display="flex" alignItems="center"><LibraryMusic sx={{ mr: 1 }} />Existing playlist</Box>} />
          <FormControlLabel value="scratch" control={<Radio />}
            label={<Box display="flex" alignItems="center"><CreateNewFolder sx={{ mr: 1 }} />New playlist</Box>} />
        </RadioGroup>

        {mode === 'existing' ? (
          playlists === null ? (
            <Box textAlign="center" my={3}><CircularProgress size={28} /></Box>
          ) : available.length === 0 ? (
            <Typography color="text.secondary">
              No playlists available. You can rotate playlists you own or collaborate on that don't already have a rotation.
            </Typography>
          ) : (
            <List sx={{ maxHeight: 280, overflow: 'auto' }} dense>
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

        <IntervalPicker value={intervalHours} onChange={setIntervalHours} />
        {/* A new playlist starts empty, so the grace period has nothing to apply to */}
        {mode === 'existing' && <GracePeriodSwitch checked={grace} onChange={setGrace} />}
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

// ---------- edit ----------

export const EditRotationDialog = ({ rotation, onClose, onSaved }) => {
  const [name, setName] = useState('');
  const [intervalHours, setIntervalHours] = useState(null);
  const [grace, setGrace] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (rotation) {
      setName(rotation.name); setIntervalHours(rotation.interval_hours);
      setGrace(rotation.grace_period); setError('');
    }
  }, [rotation]);

  const save = async () => {
    try {
      await api.updateRotation(rotation.id, { name: name.trim(), interval_hours: intervalHours, grace_period: grace });
      onSaved();
    } catch (e) {
      setError(errorMessage(e, 'Failed to save changes.'));
    }
  };

  return (
    <Dialog open={!!rotation} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit Rotation</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <TextField fullWidth label="Name" value={name} onChange={(e) => setName(e.target.value)}
          inputProps={{ maxLength: 100 }} sx={{ mt: 1 }} />
        {/* key remounts the picker so it starts from this rotation's interval */}
        {rotation && <IntervalPicker key={rotation.id} value={intervalHours} onChange={setIntervalHours} />}
        <GracePeriodSwitch checked={grace} onChange={setGrace} />
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          Changes apply right away to every song that hasn't been kept yet. Kept songs come up one
          interval after you kept them.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!name.trim() || intervalHours === null}>Save</Button>
      </DialogActions>
    </Dialog>
  );
};

// ---------- delete ----------

export const DeleteRotationDialog = ({ rotation, onClose, onDeleted }) => {
  const [error, setError] = useState('');
  useEffect(() => { setError(''); }, [rotation]);

  const confirm = async () => {
    try {
      await api.deleteRotation(rotation.id);
      onDeleted();
    } catch (e) {
      setError(errorMessage(e, 'Failed to delete the rotation.'));
    }
  };

  return (
    <Dialog open={!!rotation} onClose={onClose}>
      <DialogTitle>Delete “{rotation?.name}”?</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Typography>
          This deletes the rotation and its review history from PlayLS. Your Spotify playlist is not changed.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button color="error" variant="contained" onClick={confirm}>Delete</Button>
      </DialogActions>
    </Dialog>
  );
};

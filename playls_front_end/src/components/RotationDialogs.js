import React, { useEffect, useState } from 'react';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  List,
  ListItem,
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
import { AutoMode, CreateNewFolder, LibraryMusic, MusicNote } from '@mui/icons-material';
import { api, errorMessage } from '../api';
import { ListSkeleton } from './Skeletons';

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
export const IntervalPicker = ({ value, onChange, label = 'Review each song every' }) => {
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
      <Typography variant="subtitle2" gutterBottom>{label}</Typography>
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

// ---------- auto rotation settings ----------

export const TARGET_SIZES = [30, 50, 100, 200];
export const ROTATE_PERCENTS = [10, 20, 30, 50];
export const AUTO_DEFAULTS = { target: 50, percent: 20, intervalHours: 24 * 7 };

export const describeAuto = (target, percent, hours) => {
  const n = Math.max(1, Math.round((target * percent) / 100));
  return `Every ${formatInterval(hours)}, the ${n} oldest of ${target} songs rotate out and are replaced.`;
};

const ChoiceChips = ({ title, options, value, onChange, format }) => (
  <Box sx={{ mt: 2 }}>
    <Typography variant="subtitle2" gutterBottom>{title}</Typography>
    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
      {options.map((o) => (
        <Chip key={o} label={format(o)} onClick={() => onChange(o)}
          color={value === o ? 'primary' : 'default'} variant={value === o ? 'filled' : 'outlined'} />
      ))}
    </Stack>
  </Box>
);

export const AutoSettings = ({ target, percent, intervalHours, onTarget, onPercent, onInterval, pickerKey }) => (
  <>
    <ChoiceChips title="Keep the playlist at" options={TARGET_SIZES} value={target} onChange={onTarget}
      format={(n) => `${n} songs`} />
    <ChoiceChips title="Rotate out" options={ROTATE_PERCENTS} value={percent} onChange={onPercent}
      format={(p) => `${p}%`} />
    <IntervalPicker key={pickerKey} value={intervalHours} onChange={onInterval} label="Rotate every" />
    {intervalHours !== null && (
      <Typography variant="body2" color="text.secondary">
        {describeAuto(target, percent, intervalHours)} Songs you keep stay longer, and a song that
        rotated out can come back after at least 4 weeks.
      </Typography>
    )}
  </>
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
  const [target, setTarget] = useState(AUTO_DEFAULTS.target);
  const [percent, setPercent] = useState(AUTO_DEFAULTS.percent);
  const [autoHours, setAutoHours] = useState(AUTO_DEFAULTS.intervalHours);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setMode('existing'); setPlaylistId(null); setName(''); setDescription('');
    setIntervalHours(24 * 30); setGrace(true); setError(''); setPlaylists(null);
    setTarget(AUTO_DEFAULTS.target); setPercent(AUTO_DEFAULTS.percent); setAutoHours(AUTO_DEFAULTS.intervalHours);
    // Loaded on open so Home doesn't page through every playlist on each visit
    api.playlists()
      .then(setPlaylists)
      .catch((e) => { setPlaylists([]); setError(errorMessage(e, 'Failed to load your Spotify playlists.')); });
  }, [open]);

  const available = (playlists || []).filter((p) => p.rotatable && !p.rotation_id);
  const canCreate = mode === 'auto'
    ? autoHours !== null && name.trim() !== ''
    : intervalHours !== null && (mode === 'existing' ? !!playlistId : name.trim() !== '');

  const create = async () => {
    setSaving(true);
    setError('');
    try {
      const body = mode === 'existing'
        ? { playlist_id: playlistId, interval_hours: intervalHours, grace_period: grace }
        : mode === 'auto'
          ? { kind: 'auto', name: name.trim(), description: description.trim() || null,
              target_size: target, rotate_percent: percent, interval_hours: autoHours }
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
          <FormControlLabel value="auto" control={<Radio />}
            label={<Box display="flex" alignItems="center"><AutoMode sx={{ mr: 1 }} />Auto-restocking</Box>} />
        </RadioGroup>

        {mode === 'existing' ? (
          playlists === null ? (
            <ListSkeleton count={5} dense />
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
              {mode === 'auto'
                ? 'Creates a new private Spotify playlist and fills it with songs picked for you. PlayLS keeps it turning over on its own; reviewing is optional.'
                : 'Creates a new private, empty Spotify playlist. Add songs to it in Spotify and PlayLS picks them up.'}
            </Typography>
            <TextField fullWidth label="Playlist name" value={name} onChange={(e) => setName(e.target.value)}
              inputProps={{ maxLength: 100 }} sx={{ mb: 2 }} required />
            <TextField fullWidth label="Description (optional)" value={description}
              onChange={(e) => setDescription(e.target.value)} inputProps={{ maxLength: 300 }} multiline rows={2} />
          </>
        )}

        {mode === 'auto' ? (
          <AutoSettings target={target} percent={percent} intervalHours={autoHours}
            onTarget={setTarget} onPercent={setPercent} onInterval={setAutoHours} pickerKey="auto" />
        ) : (
          <IntervalPicker key="manual" value={intervalHours} onChange={setIntervalHours} />
        )}
        {/* A new playlist starts empty, so the grace period has nothing to apply to */}
        {mode === 'existing' && <GracePeriodSwitch checked={grace} onChange={setGrace} />}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>Cancel</Button>
        <Button variant="contained" onClick={create} disabled={saving || !canCreate}>
          {saving ? (mode === 'auto' ? 'Filling playlist…' : 'Creating…') : 'Create Rotation'}
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
  const [target, setTarget] = useState(AUTO_DEFAULTS.target);
  const [percent, setPercent] = useState(AUTO_DEFAULTS.percent);
  const [error, setError] = useState('');
  const isAuto = rotation?.kind === 'auto';

  useEffect(() => {
    if (rotation) {
      setName(rotation.name); setIntervalHours(rotation.interval_hours);
      setGrace(rotation.grace_period); setError('');
      setTarget(rotation.target_size || AUTO_DEFAULTS.target);
      setPercent(rotation.rotate_percent || AUTO_DEFAULTS.percent);
    }
  }, [rotation]);

  const save = async () => {
    try {
      const body = isAuto
        ? { name: name.trim(), interval_hours: intervalHours, target_size: target, rotate_percent: percent }
        : { name: name.trim(), interval_hours: intervalHours, grace_period: grace };
      await api.updateRotation(rotation.id, body);
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
        {rotation && isAuto && (
          <>
            <AutoSettings target={target} percent={percent} intervalHours={intervalHours}
              onTarget={setTarget} onPercent={setPercent} onInterval={setIntervalHours} pickerKey={rotation.id} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              A bigger target fills up right away; a smaller one trims the oldest songs at the next rotation.
            </Typography>
          </>
        )}
        {rotation && !isAuto && (
          <>
            <IntervalPicker key={rotation.id} value={intervalHours} onChange={setIntervalHours} />
            <GracePeriodSwitch checked={grace} onChange={setGrace} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              Changes apply right away to every song that hasn't been kept yet. Kept songs come up one
              interval after you kept them.
            </Typography>
          </>
        )}
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

// ---------- reset due dates ----------

export const ResetDueDialog = ({ rotation, onClose, onDone }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setError(''); setBusy(false); }, [rotation]);

  const confirm = async () => {
    setBusy(true);
    try {
      await api.resetDue(rotation.id);
      onDone();
    } catch (e) {
      setError(errorMessage(e, "Couldn't reset due dates."));
      setBusy(false);
    }
  };

  return (
    <Dialog open={!!rotation} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Reset all due dates?</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Typography paragraph>
          Every song in “{rotation?.name}” will be treated as just reviewed, so nothing is due now.
          Each song comes up again {rotation ? `in ${formatInterval(rotation.interval_hours)}` : 'one interval from now'}.
        </Typography>
        <Typography color="text.secondary" variant="body2">
          {rotation?.due_count > 0
            ? `${rotation.due_count} song${rotation.due_count === 1 ? ' is' : 's are'} due right now. `
            : ''}
          This can't be undone. Your Spotify playlist isn't changed.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button color="warning" variant="contained" onClick={confirm} disabled={busy}>
          {busy ? 'Resetting…' : 'Reset due dates'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

// ---------- remove unavailable songs ----------

export const RemoveUnplayableDialog = ({ rotation, onClose, onDone }) => {
  const [tracks, setTracks] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (!rotation) return;
    setTracks(null); setError(''); setBusy(false); setResult(null);
    api.unplayable(rotation.id)
      .then((r) => setTracks(r.tracks))
      .catch((e) => { setError(errorMessage(e, "Couldn't check the playlist with Spotify.")); setTracks([]); });
  }, [rotation]);

  const confirm = async () => {
    setBusy(true);
    try {
      setResult(await api.removeUnplayable(rotation.id));
    } catch (e) {
      setError(errorMessage(e, "Couldn't remove the songs."));
    } finally {
      setBusy(false);
    }
  };

  const close = () => { if (result) onDone(); else onClose(); };

  return (
    <Dialog open={!!rotation} onClose={busy ? undefined : close} maxWidth="sm" fullWidth>
      <DialogTitle>Remove unavailable songs</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {result ? (
          <Alert severity={result.flushed ? 'success' : 'warning'}>
            {result.flushed
              ? `Removed ${result.removed} song${result.removed === 1 ? '' : 's'} from the rotation and your Spotify playlist.`
              : `Removed ${result.removed} from the rotation. Spotify couldn't be reached, so they'll be taken out of the playlist at the next sync.`}
          </Alert>
        ) : tracks === null ? (
          <Box textAlign="center" my={3}>
            <Typography color="text.secondary" variant="body2" mb={1}>Checking every song with Spotify…</Typography>
            <ListSkeleton count={3} dense />
          </Box>
        ) : tracks.length === 0 ? (
          <Typography>Every song in “{rotation?.name}” is playable. Nothing to remove.</Typography>
        ) : (
          <>
            <Typography paragraph>
              {tracks.length} song{tracks.length === 1 ? ' is' : 's are'} still in the playlist but no longer
              playable on Spotify (greyed out). Remove {tracks.length === 1 ? 'it' : 'them'} from the rotation and the
              Spotify playlist?
            </Typography>
            <List dense sx={{ maxHeight: 280, overflow: 'auto' }}>
              {tracks.map((t) => (
                <ListItem key={t.track_id} disableGutters>
                  <ListItemAvatar>
                    <Avatar variant="rounded" src={t.image_url || undefined}><MusicNote /></Avatar>
                  </ListItemAvatar>
                  <ListItemText primary={t.title} secondary={t.artists} />
                </ListItem>
              ))}
            </List>
          </>
        )}
      </DialogContent>
      <DialogActions>
        {result || (tracks && tracks.length === 0) ? (
          <Button variant="contained" onClick={close}>Done</Button>
        ) : (
          <>
            <Button onClick={onClose} disabled={busy}>Cancel</Button>
            <Button color="error" variant="contained" onClick={confirm} disabled={busy || !tracks}>
              {busy ? 'Removing…' : `Remove ${tracks ? tracks.length : ''} song${tracks && tracks.length === 1 ? '' : 's'}`}
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
};

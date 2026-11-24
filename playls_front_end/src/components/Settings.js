import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Card,
  Checkbox,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Avatar,
  FormControlLabel,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Snackbar,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { DarkMode, LightMode, MusicNote, SettingsBrightness } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { useColorMode } from '../colorMode';
import { api, errorMessage } from '../api';
import { Layout } from './Layout';
import { IntervalPicker } from './RotationDialogs';
import {
  DECK_OPTIONS,
  DISCOVERY_OPTIONS,
  MoreOptions,
  NOT_NOW_OPTIONS,
  ORDER_OPTIONS,
  OptionChips,
  RECOVERY_OPTIONS,
  SKIP_HOLD_OPTIONS,
  SUPER_KEEP_OPTIONS,
} from './SettingsControls';
import { ListSkeleton } from './Skeletons';

const DEFAULT_LIMIT = 50;
const REVIEW_EXTRAS = ['super_keep_multiplier', 'skip_hold_days', 'review_order', 'default_interval_hours'];
const RESTOCK_EXTRAS = ['deck_size', 'discovery_percent', 'not_now_percent', 'bring_back_recovery_days'];

const AppearanceCard = () => {
  const { preference, setPreference } = useColorMode();
  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Appearance</Typography>
        <ToggleButtonGroup exclusive value={preference} onChange={(_, v) => v && setPreference(v)}
          aria-label="Color mode" sx={{ flexWrap: 'wrap' }}>
          <ToggleButton value="light"><LightMode fontSize="small" sx={{ mr: 1 }} />Light</ToggleButton>
          <ToggleButton value="dark"><DarkMode fontSize="small" sx={{ mr: 1 }} />Dark</ToggleButton>
          <ToggleButton value="system"><SettingsBrightness fontSize="small" sx={{ mr: 1 }} />System</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="body2" color="text.secondary" mt={1.5}>
          System follows your device's setting. Saved in this browser.
        </Typography>
      </CardContent>
    </Card>
  );
};

const ResetLink = ({ onClick }) => (
  <Button size="small" color="inherit" onClick={onClick} sx={{ mt: 2, color: 'text.secondary' }}>
    Reset these to defaults
  </Button>
);

// The daily limit up front; the rest of how reviewing works is under "More options"
const ReviewingCard = ({ settings, save }) => {
  const [noLimit, setNoLimit] = useState(false);
  const [amount, setAmount] = useState(String(DEFAULT_LIMIT));
  const [pickerKey, setPickerKey] = useState(0);
  const intervalTimer = useRef(null);
  const loaded = !!settings;
  const saved = settings?.review_limit;

  useEffect(() => {
    if (!settings) return;
    setNoLimit(settings.review_limit === null);
    setAmount(String(settings.review_limit ?? DEFAULT_LIMIT));
  }, [settings?.review_limit]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => clearTimeout(intervalTimer.current), []);

  const n = Number(amount);
  const valid = noLimit || (Number.isInteger(n) && n >= 1 && n <= 1000);
  const value = noLimit ? null : n;
  const dirty = loaded && valid && value !== saved;

  // The interval picker reports every keystroke; save once typing pauses
  const saveInterval = (hours) => {
    clearTimeout(intervalTimer.current);
    if (hours === null || hours === settings.default_interval_hours) return;
    intervalTimer.current = setTimeout(() => save({ default_interval_hours: hours }), 600);
  };

  const reset = async () => {
    await save(Object.fromEntries(REVIEW_EXTRAS.map((k) => [k, null])));
    setPickerKey((k) => k + 1); // re-read the restored interval
  };

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Reviewing</Typography>
        <Typography variant="subtitle2">Daily review limit</Typography>
        <Typography color="text.secondary" paragraph>
          The most songs each rotation offers for review per day, so a big backlog doesn't arrive all at
          once. After finishing a day's batch you can still choose to review more.
        </Typography>
        <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
          <TextField
            label="Songs per day"
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            disabled={!loaded || noLimit}
            error={!valid}
            helperText={!valid ? 'Between 1 and 1000' : ' '}
            inputProps={{ min: 1, max: 1000, step: 1 }}
            sx={{ width: 160 }}
          />
          <FormControlLabel
            control={<Checkbox checked={noLimit} disabled={!loaded} onChange={(e) => setNoLimit(e.target.checked)} />}
            label="No limit"
            sx={{ mb: 2.5 }}
          />
          <Button variant="contained" onClick={() => save({ review_limit: value })} disabled={!dirty} sx={{ mb: 2.5 }}>
            Save
          </Button>
        </Box>

        {loaded && (
          <MoreOptions>
            <Typography variant="body2" color="text.secondary">
              These apply to every rotation. A rotation can choose differently in its own settings.
            </Typography>
            <OptionChips title="Super keep" help="How much longer a super kept song waits before it comes back."
              options={SUPER_KEEP_OPTIONS} value={settings.super_keep_multiplier}
              onChange={(v) => save({ super_keep_multiplier: v })} />
            <OptionChips title="Skipped songs come back" options={SKIP_HOLD_OPTIONS} value={settings.skip_hold_days}
              onChange={(v) => save({ skip_hold_days: v })} />
            <OptionChips title="Review order" help="Which due songs come up first."
              options={ORDER_OPTIONS} value={settings.review_order} onChange={(v) => save({ review_order: v })} />
            <IntervalPicker key={pickerKey} value={settings.default_interval_hours} onChange={saveInterval}
              label="Starting interval for new rotations" />
            <ResetLink onClick={reset} />
          </MoreOptions>
        )}
      </CardContent>
    </Card>
  );
};

// How Restock chooses songs; everything is under "More options"
const RestockingCard = ({ settings, save }) => (
  <Card sx={{ mb: 3 }}>
    <CardContent>
      <Typography variant="h6" gutterBottom>Restocking</Typography>
      <Typography color="text.secondary">How Restock picks songs for you, across every rotation.</Typography>
      {settings && (
        <MoreOptions>
          <OptionChips title="Songs per deck" options={DECK_OPTIONS} value={settings.deck_size}
            onChange={(v) => save({ deck_size: v })} />
          <OptionChips title="For you" help="How many suggestions are new to you, rather than songs you already play."
            options={DISCOVERY_OPTIONS} value={settings.discovery_percent}
            onChange={(v) => save({ discovery_percent: v })} />
          <OptionChips title="Not now pushes a song back" help="How much less often a song comes up after you pass on it."
            options={NOT_NOW_OPTIONS} value={settings.not_now_percent}
            onChange={(v) => save({ not_now_percent: v })} />
          <OptionChips title="Removed songs are back in Bring back"
            help="Removed songs start rare in Bring back and become more likely over time."
            options={RECOVERY_OPTIONS} value={settings.bring_back_recovery_days}
            onChange={(v) => save({ bring_back_recovery_days: v })} />
          <ResetLink onClick={() => save(Object.fromEntries(RESTOCK_EXTRAS.map((k) => [k, null])))} />
        </MoreOptions>
      )}
    </CardContent>
  </Card>
);

// Songs the user asked Restock to stop suggesting, with a way to undo each
const BlockedSongsCard = () => {
  const [songs, setSongs] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.blockedSongs().then(setSongs)
      .catch((e) => { setError(errorMessage(e, 'Failed to load.')); setSongs([]); });
  }, []);

  const resume = async (song) => {
    try {
      await api.unblockSong(song.track_id);
      setSongs((list) => list.filter((s) => s.track_id !== song.track_id));
    } catch (e) {
      setError(errorMessage(e, "Couldn't resume that song."));
    }
  };

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Songs you've stopped suggesting</Typography>
        <Typography color="text.secondary" paragraph>
          These never come up in Restock. They stay in your rotation history, and you can still add them by search.
        </Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {songs === null && <ListSkeleton count={2} dense />}
        {songs && songs.length === 0 && <Typography color="text.secondary">None.</Typography>}
        {songs && songs.length > 0 && (
          <List dense sx={{ maxHeight: 320, overflow: 'auto' }}>
            {songs.map((s) => (
              <ListItem key={s.track_id} disableGutters
                secondaryAction={<Button size="small" onClick={() => resume(s)}>Resume suggesting</Button>}>
                <ListItemAvatar>
                  <Avatar variant="rounded" src={s.image_url || undefined}><MusicNote /></Avatar>
                </ListItemAvatar>
                <ListItemText primary={s.title} secondary={s.artists} sx={{ pr: 18 }} />
              </ListItem>
            ))}
          </List>
        )}
      </CardContent>
    </Card>
  );
};

const Settings = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');
  const [settings, setSettings] = useState(null);
  const [toast, setToast] = useState('');

  useEffect(() => {
    api.settings().then(setSettings).catch((e) => setError(errorMessage(e, 'Failed to load settings.')));
  }, []);

  // Save some settings right away (only the fields given change)
  const save = useCallback(async (fields) => {
    setError('');
    try {
      setSettings(await api.updateSettings(fields));
      setToast('Saved');
    } catch (e) {
      setError(errorMessage(e, 'Failed to save settings.'));
    }
  }, []);

  const signOut = async () => {
    await logout();
    navigate('/');
  };

  const deleteAccount = async () => {
    try {
      await api.deleteAccount();
      await logout();
      navigate('/');
    } catch (e) {
      setError(errorMessage(e, 'Failed to delete your account.'));
      setConfirmDelete(false);
    }
  };

  return (
    <Layout maxWidth="sm" back="/">
      <Typography variant="h4" component="h1" gutterBottom>Settings</Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <AppearanceCard />
      <ReviewingCard settings={settings} save={save} />
      <RestockingCard settings={settings} save={save} />
      <BlockedSongsCard />

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>Account</Typography>
          <Typography color="text.secondary" paragraph>
            Signed in with Spotify as {user?.display_name || user?.spotify_id}
          </Typography>
          <Button variant="outlined" onClick={signOut}>Log out</Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>Delete account</Typography>
          <Typography color="text.secondary" paragraph>
            Removes your rotations, review history and stored Spotify tokens from PlayLS.
            Your Spotify playlists are not changed.
          </Typography>
          <Button variant="outlined" color="error" onClick={() => setConfirmDelete(true)}>
            Delete my PlayLS account
          </Button>
        </CardContent>
      </Card>

      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)}>
        <DialogTitle>Delete your PlayLS account?</DialogTitle>
        <DialogContent>
          <Typography>This can't be undone. Your Spotify playlists stay as they are.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={deleteAccount}>Delete</Button>
        </DialogActions>
      </Dialog>

      <Snackbar open={!!toast} autoHideDuration={1500} onClose={() => setToast('')} message={toast}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }} />
    </Layout>
  );
};

export default Settings;

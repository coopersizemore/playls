import React, { useEffect, useState } from 'react';
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
import { ListSkeleton } from './Skeletons';

const DEFAULT_LIMIT = 50;

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

// Songs offered for review per rotation per day (null = no limit)
const ReviewLimitCard = () => {
  const [loaded, setLoaded] = useState(false);
  const [noLimit, setNoLimit] = useState(false);
  const [amount, setAmount] = useState(String(DEFAULT_LIMIT));
  const [saved, setSaved] = useState(null);
  const [status, setStatus] = useState({ type: '', text: '' });

  useEffect(() => {
    api.settings()
      .then(({ review_limit: limit }) => {
        setNoLimit(limit === null);
        setAmount(String(limit ?? DEFAULT_LIMIT));
        setSaved(limit);
        setLoaded(true);
      })
      .catch((e) => setStatus({ type: 'error', text: errorMessage(e, 'Failed to load settings.') }));
  }, []);

  const n = Number(amount);
  const valid = noLimit || (Number.isInteger(n) && n >= 1 && n <= 1000);
  const value = noLimit ? null : n;
  const dirty = loaded && valid && value !== saved;

  const save = async () => {
    try {
      const { review_limit: limit } = await api.updateSettings({ review_limit: value });
      setSaved(limit);
      setStatus({ type: 'success', text: 'Saved.' });
    } catch (e) {
      setStatus({ type: 'error', text: errorMessage(e, 'Failed to save settings.') });
    }
  };

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Typography variant="h6" gutterBottom>Daily review limit</Typography>
        <Typography color="text.secondary" paragraph>
          The most songs each rotation offers for review per day, most overdue first, so a big backlog
          doesn't arrive all at once. After finishing a day's batch you can still choose to review more.
        </Typography>
        {status.text && <Alert severity={status.type} sx={{ mb: 2 }}>{status.text}</Alert>}
        <Box display="flex" alignItems="center" gap={2} flexWrap="wrap">
          <TextField
            label="Songs per day"
            type="number"
            value={amount}
            onChange={(e) => { setAmount(e.target.value); setStatus({ type: '', text: '' }); }}
            disabled={!loaded || noLimit}
            error={!valid}
            helperText={!valid ? 'Between 1 and 1000' : ' '}
            inputProps={{ min: 1, max: 1000, step: 1 }}
            sx={{ width: 160 }}
          />
          <FormControlLabel
            control={<Checkbox checked={noLimit} disabled={!loaded}
              onChange={(e) => { setNoLimit(e.target.checked); setStatus({ type: '', text: '' }); }} />}
            label="No limit"
            sx={{ mb: 2.5 }}
          />
          <Button variant="contained" onClick={save} disabled={!dirty} sx={{ mb: 2.5 }}>Save</Button>
        </Box>
      </CardContent>
    </Card>
  );
};

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
      <ReviewLimitCard />
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
    </Layout>
  );
};

export default Settings;

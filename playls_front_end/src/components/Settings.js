import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material';
import { useAuth } from '../contexts/AuthContext';
import { api, errorMessage } from '../api';
import { Layout } from './Layout';

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
    <Layout maxWidth="sm">
      <Typography variant="h4" component="h1" gutterBottom>Settings</Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

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

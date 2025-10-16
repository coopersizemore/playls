import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import {
  Container,
  Typography,
  Card,
  CardContent,
  Switch,
  FormControlLabel,
  Slider,
  Button,
  Divider,
  Box,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
} from '@mui/material';
import {
  Delete,
  Logout,
  MusicNote,
  Notifications,
} from '@mui/icons-material';

const Settings = () => {
  const { user, logout } = useAuth();
  const [settings, setSettings] = useState({
    notifications: true,
    autoRotate: false,
    rotationInterval: 30,
    skipThreshold: 3,
    emailUpdates: false
  });
  const [openDeleteDialog, setOpenDeleteDialog] = useState(false);

  const handleSettingChange = (setting) => (event) => {
    setSettings({
      ...settings,
      [setting]: event.target.checked !== undefined ? event.target.checked : event.target.value
    });
  };

  const handleDeleteAccount = () => {
    // API call to delete account
    console.log('Deleting account...');
    setOpenDeleteDialog(false);
    logout();
  };

  return (
    <Container maxWidth="md" sx={{ mt: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Settings
      </Typography>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Account
          </Typography>
          <List>
            <ListItem>
              <ListItemText
                primary="User ID"
                secondary={user?.id || 'Not logged in'}
              />
            </ListItem>
            <ListItem>
              <ListItemText
                primary="Connected Account"
                secondary="Spotify"
              />
            </ListItem>
          </List>
        </CardContent>
      </Card>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Rotation Settings
          </Typography>
          
          <FormControlLabel
            control={
              <Switch
                checked={settings.notifications}
                onChange={handleSettingChange('notifications')}
              />
            }
            label="Email notifications for rotation reviews"
          />
          
          <FormControlLabel
            control={
              <Switch
                checked={settings.autoRotate}
                onChange={handleSettingChange('autoRotate')}
              />
            }
            label="Auto-add songs to review queue"
          />
          
          <Box sx={{ mt: 3 }}>
            <Typography gutterBottom>
              Default rotation interval: {settings.rotationInterval} days
            </Typography>
            <Slider
              value={settings.rotationInterval}
              onChange={handleSettingChange('rotationInterval')}
              min={7}
              max={90}
              step={7}
              marks={[
                { value: 7, label: '7 days' },
                { value: 30, label: '30 days' },
                { value: 60, label: '60 days' },
                { value: 90, label: '90 days' }
              ]}
            />
          </Box>
          
          <Box sx={{ mt: 3 }}>
            <Typography gutterBottom>
              Skip threshold: {settings.skipThreshold} times
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Automatically suggest removing songs you skip this many times
            </Typography>
            <Slider
              value={settings.skipThreshold}
              onChange={handleSettingChange('skipThreshold')}
              min={1}
              max={10}
              step={1}
              marks={[
                { value: 1, label: '1' },
                { value: 5, label: '5' },
                { value: 10, label: '10' }
              ]}
            />
          </Box>
        </CardContent>
      </Card>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Notifications
          </Typography>
          
          <FormControlLabel
            control={
              <Switch
                checked={settings.emailUpdates}
                onChange={handleSettingChange('emailUpdates')}
              />
            }
            label="Email updates about new features"
          />
        </CardContent>
      </Card>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Data & Privacy
          </Typography>
          
          <Button
            variant="outlined"
            color="primary"
            sx={{ mr: 2 }}
          >
            Export My Data
          </Button>
          
          <Button
            variant="outlined"
            color="error"
            onClick={() => setOpenDeleteDialog(true)}
          >
            Delete Account
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            About
          </Typography>
          <Typography variant="body2" color="text.secondary">
            PlayLS v1.0.0
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Keep your Spotify playlists fresh by rotating songs in and out
          </Typography>
        </CardContent>
      </Card>

      <Box sx={{ mt: 4, textAlign: 'center' }}>
        <Button
          variant="contained"
          color="error"
          startIcon={<Logout />}
          onClick={logout}
        >
          Logout
        </Button>
      </Box>

      <Dialog open={openDeleteDialog} onClose={() => setOpenDeleteDialog(false)}>
        <DialogTitle>Delete Account</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete your account? This action cannot be undone.
            All your rotations and data will be permanently deleted.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDeleteDialog(false)}>Cancel</Button>
          <Button 
            onClick={handleDeleteAccount} 
            color="error"
            variant="contained"
          >
            Delete Account
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default Settings;


import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';
import {
  Container,
  Typography,
  Button,
  Grid,
  Card,
  CardContent,
  CardActions,
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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Box,
  Chip,
  Stepper,
  Step,
  StepLabel,
  RadioGroup,
  FormControlLabel,
  Radio,
  Alert,
} from '@mui/material';
import {
  Add,
  Delete,
  MusicNote,
  PlayArrow,
  LibraryMusic,
  CreateNewFolder,
} from '@mui/icons-material';

import { API_BASE } from '../api';

const Rotation = () => {
  const { user } = useAuth();
  const [playlists, setPlaylists] = useState([]);
  const [rotations, setRotations] = useState([]);
  const [selectedPlaylist, setSelectedPlaylist] = useState(null);
  const [rotationInterval, setRotationInterval] = useState(30);
  const [openDialog, setOpenDialog] = useState(false);
  const [loading, setLoading] = useState(false);
  
  // New state for rotation creation flow
  const [activeStep, setActiveStep] = useState(0);
  const [creationType, setCreationType] = useState('');
  const [newPlaylistName, setNewPlaylistName] = useState('');
  const [newPlaylistDescription, setNewPlaylistDescription] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (user) {
      fetchPlaylists();
      fetchRotations();
    }
  }, [user]);

  const fetchPlaylists = async () => {
    try {
      const response = await axios.get(`${API_BASE}/spotify/playlists`);
      setPlaylists(response.data.items || []);
    } catch (error) {
      console.error('Failed to fetch playlists:', error);
      setError('Failed to fetch playlists. Please try again.');
    }
  };

  const fetchRotations = async () => {
    console.log('Fetching rotations...');
    try {
      const response = await axios.get(`${API_BASE}/user/me/rotations`);
      setRotations(response.data || []);
      console.log('Rotations fetched successfully:', response.data);
    } catch (error) {
      console.error('Failed to fetch rotations:', error);
      setError('Failed to fetch rotations. Please try again.');
    }
  };

  const createRotationFromExisting = async () => {
    try {
      setLoading(true);
      const response = await axios.post(`${API_BASE}/rotation/`, {
        name: `${selectedPlaylist.name}`,
        description: `"${selectedPlaylist.name}"`,
        last_rotated_at: null,
        rotation_interval: rotationInterval,
        playlist_id: selectedPlaylist.id
      });
      
      console.log('Rotation created from existing playlist:', response.data);
      handleDialogClose();
      setError('');
    } catch (error) {
      console.error('Failed to create rotation:', error);
      setError('Failed to create rotation. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const createRotationFromScratch = async () => {
    try {
      setLoading(true);

      // create a rotation for this new playlist
      const rotationResponse = await axios.post(`${API_BASE}/rotation/`, {
        name: `${newPlaylistName}`,
        description: `"${newPlaylistDescription}"`,
        last_rotated_at: null,
        rotation_interval: rotationInterval,
      });
      
      console.log('Rotation created from scratch:', rotationResponse.data);
      
      // Refresh the playlists to show the new one
      await fetchPlaylists();
      
      handleDialogClose();
      setError('');
    } catch (error) {
      console.error('Failed to create rotation from scratch:', error);
      setError('Failed to create playlist and rotation. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateRotation = () => {
    setError('');
    if (creationType === 'existing' && selectedPlaylist) {
      createRotationFromExisting();
    } else if (creationType === 'scratch' && newPlaylistName.trim()) {
      createRotationFromScratch();
    }
  };

  const handleDialogClose = () => {
    setOpenDialog(false);
    setActiveStep(0);
    setCreationType('');
    setSelectedPlaylist(null);
    setNewPlaylistName('');
    setNewPlaylistDescription('');
    setError('');
  };

  const handleNext = () => {
    setActiveStep((prevActiveStep) => prevActiveStep + 1);
  };

  const handleBack = () => {
    setActiveStep((prevActiveStep) => prevActiveStep - 1);
  };

  const canProceedToNext = () => {
    if (activeStep === 0) return creationType !== '';
    if (activeStep === 1) {
      if (creationType === 'existing') return selectedPlaylist !== null;
      if (creationType === 'scratch') return newPlaylistName.trim() !== '';
    }
    return true;
  };

  const canCreateRotation = () => {
    if (creationType === 'existing') return selectedPlaylist !== null;
    if (creationType === 'scratch') return newPlaylistName.trim() !== '';
    return false;
  };

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Manage Rotations
      </Typography>
      
      <Box sx={{ mb: 3 }}>
        <Button
          variant="contained"
          size="large"
          startIcon={<Add />}
          onClick={() => setOpenDialog(true)}
          sx={{ mr: 2 }}
        >
          Create New Rotation
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Grid container spacing={3}>
        <Grid item xs={12} md={8}>
          <Typography variant="h6" gutterBottom>
            Your Playlists
          </Typography>
          <List>
            {playlists.map((playlist) => (
              <Card key={playlist.id} sx={{ mb: 2 }}>
                <CardContent>
                  <Box display="flex" alignItems="center" mb={1}>
                    <MusicNote color="primary" sx={{ mr: 1 }} />
                    <Typography variant="h6">{playlist.name}</Typography>
                    <Chip 
                      label={`${playlist.tracks.total} tracks`} 
                      size="small" 
                      sx={{ ml: 2 }}
                    />
                  </Box>
                  <Typography color="text.secondary" variant="body2">
                    {playlist.description || 'No description'}
                  </Typography>
                </CardContent>
                <CardActions>
                  <Button
                    size="small"
                    startIcon={<PlayArrow />}
                    onClick={() => {
                      // Navigate to playlist details or preview
                    }}
                  >
                    Preview
                  </Button>
                </CardActions>
              </Card>
            ))}
          </List>
        </Grid>
        
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Active Rotations
              </Typography>
              <List>
            {rotations.map((rotation) => (
              <Card key={rotation.id} sx={{ mb: 2 }}>
                <CardContent>
                  <Box display="flex" alignItems="center" mb={1}>
                    <MusicNote color="primary" sx={{ mr: 1 }} />
                    <Typography variant="h6">{rotation.name}</Typography>
                    <Chip 
                      // label={`${rotation.tracks.total} tracks`} 
                      size="small" 
                      sx={{ ml: 2 }}
                    />
                  </Box>
                  <Typography color="text.secondary" variant="body2">
                    {rotation.description || 'No description'}
                  </Typography>
                </CardContent>
                <CardActions>
                  <Button
                    size="small"
                    startIcon={<PlayArrow />}
                    onClick={() => {
                      // Navigate to playlist details or preview
                    }}
                  >
                    Preview
                  </Button>
                </CardActions>
              </Card>
            ))}
          </List>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Dialog open={openDialog} onClose={handleDialogClose} maxWidth="md" fullWidth>
        <DialogTitle>Create New Rotation</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
              <Step>
                <StepLabel>Choose Creation Method</StepLabel>
              </Step>
              <Step>
                <StepLabel>Configure Details</StepLabel>
              </Step>
              <Step>
                <StepLabel>Set Rotation Settings</StepLabel>
              </Step>
            </Stepper>

            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}

            {activeStep === 0 && (
              <Box>
                <Typography variant="h6" gutterBottom>
                  How would you like to create your rotation?
                </Typography>
                <RadioGroup
                  value={creationType}
                  onChange={(e) => setCreationType(e.target.value)}
                >
                  <Card sx={{ mb: 2, border: creationType === 'existing' ? 2 : 1, borderColor: creationType === 'existing' ? 'primary.main' : 'divider' }}>
                    <CardContent>
                      <FormControlLabel
                        value="existing"
                        control={<Radio />}
                        label={
                          <Box display="flex" alignItems="center">
                            <LibraryMusic sx={{ mr: 1 }} />
                            <Box>
                              <Typography variant="subtitle1">From Existing Playlist</Typography>
                              <Typography variant="body2" color="text.secondary">
                                Choose one of your existing Spotify playlists to create a rotation
                              </Typography>
                            </Box>
                          </Box>
                        }
                      />
                    </CardContent>
                  </Card>
                  
                  <Card sx={{ border: creationType === 'scratch' ? 2 : 1, borderColor: creationType === 'scratch' ? 'primary.main' : 'divider' }}>
                    <CardContent>
                      <FormControlLabel
                        value="scratch"
                        control={<Radio />}
                        label={
                          <Box display="flex" alignItems="center">
                            <CreateNewFolder sx={{ mr: 1 }} />
                            <Box>
                              <Typography variant="subtitle1">Create From Scratch</Typography>
                              <Typography variant="body2" color="text.secondary">
                                Create a new empty Spotify playlist and set up rotation for it
                              </Typography>
                            </Box>
                          </Box>
                        }
                      />
                    </CardContent>
                  </Card>
                </RadioGroup>
              </Box>
            )}

            {activeStep === 1 && creationType === 'existing' && (
              <Box>
                <Typography variant="h6" gutterBottom>
                  Select a Playlist
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Choose which existing playlist you'd like to create a rotation for:
                </Typography>
                <Box sx={{ maxHeight: 300, overflow: 'auto' }}>
                  {playlists.map((playlist) => (
                    <Card 
                      key={playlist.id} 
                      sx={{ 
                        mb: 1, 
                        cursor: 'pointer',
                        border: selectedPlaylist?.id === playlist.id ? 2 : 1,
                        borderColor: selectedPlaylist?.id === playlist.id ? 'primary.main' : 'divider'
                      }}
                      onClick={() => setSelectedPlaylist(playlist)}
                    >
                      <CardContent sx={{ py: 1 }}>
                        <Box display="flex" alignItems="center">
                          <MusicNote color="primary" sx={{ mr: 1 }} />
                          <Box flexGrow={1}>
                            <Typography variant="subtitle2">{playlist.name}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              {playlist.tracks?.total || 0} tracks
                            </Typography>
                          </Box>
                          {selectedPlaylist?.id === playlist.id && (
                            <Chip label="Selected" color="primary" size="small" />
                          )}
                        </Box>
                      </CardContent>
                    </Card>
                  ))}
                </Box>
              </Box>
            )}

            {activeStep === 1 && creationType === 'scratch' && (
              <Box>
                <Typography variant="h6" gutterBottom>
                  Create New Playlist
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  This will create a new empty playlist on your Spotify account:
                </Typography>
                <TextField
                  fullWidth
                  label="Playlist Name"
                  value={newPlaylistName}
                  onChange={(e) => setNewPlaylistName(e.target.value)}
                  sx={{ mb: 2 }}
                  required
                />
                <TextField
                  fullWidth
                  label="Playlist Description (Optional)"
                  value={newPlaylistDescription}
                  onChange={(e) => setNewPlaylistDescription(e.target.value)}
                  multiline
                  rows={3}
                />
              </Box>
            )}

            {activeStep === 2 && (
              <Box>
                <Typography variant="h6" gutterBottom>
                  Rotation Settings
                </Typography>
                {creationType === 'existing' && selectedPlaylist && (
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="subtitle2" gutterBottom>
                      Selected Playlist: {selectedPlaylist.name}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedPlaylist.tracks?.total || 0} tracks
                    </Typography>
                  </Box>
                )}
                
                {creationType === 'scratch' && (
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="subtitle2" gutterBottom>
                      New Playlist: {newPlaylistName}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {newPlaylistDescription || 'No description'}
                    </Typography>
                  </Box>
                )}
                
                <FormControl fullWidth sx={{ mt: 2 }}>
                  <InputLabel>Rotation Interval</InputLabel>
                  <Select
                    value={rotationInterval}
                    onChange={(e) => setRotationInterval(e.target.value)}
                  >
                    <MenuItem value={7}>Every 7 days</MenuItem>
                    <MenuItem value={14}>Every 14 days</MenuItem>
                    <MenuItem value={30}>Every 30 days</MenuItem>
                    <MenuItem value={60}>Every 60 days</MenuItem>
                    <MenuItem value={90}>Every 90 days</MenuItem>
                  </Select>
                </FormControl>
                
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                  Songs will be added to your review queue based on when they were added to the playlist.
                  You can review and remove songs that no longer fit your taste.
                </Typography>
              </Box>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleDialogClose}>Cancel</Button>
          <Box sx={{ flex: '1 1 auto' }} />
          {activeStep !== 0 && (
            <Button onClick={handleBack} sx={{ mr: 1 }}>
              Back
            </Button>
          )}
          {activeStep < 2 ? (
            <Button
              variant="contained"
              onClick={handleNext}
              disabled={!canProceedToNext()}
            >
              Next
            </Button>
          ) : (
            <Button
              variant="contained"
              onClick={handleCreateRotation}
              disabled={loading || !canCreateRotation()}
            >
              {loading ? 'Creating...' : 'Create Rotation'}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default Rotation;


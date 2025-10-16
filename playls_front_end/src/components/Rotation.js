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
} from '@mui/material';
import {
  Add,
  Delete,
  MusicNote,
  PlayArrow,
} from '@mui/icons-material';

const Rotation = () => {
  const { user } = useAuth();
  const [playlists, setPlaylists] = useState([]);
  const [selectedPlaylist, setSelectedPlaylist] = useState(null);
  const [rotationInterval, setRotationInterval] = useState(30);
  const [openDialog, setOpenDialog] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user) {
      fetchPlaylists();
    }
  }, [user]);

  const fetchPlaylists = async () => {
    try {
      const response = await axios.get(`http://localhost:8000/user/playlists?user_id=${user.id}`);
      setPlaylists(response.data.items || []);
    } catch (error) {
      console.error('Failed to fetch playlists:', error);
    }
  };

  const createRotation = async (playlistId) => {
    try {
      setLoading(true);
      const response = await axios.post('http://localhost:8000/rotation/create', {
        user_id: user.id,
        playlist_id: playlistId,
        rotation_interval: rotationInterval
      });
      
      console.log('Rotation created:', response.data);
      setOpenDialog(false);
      // Show success message or redirect
    } catch (error) {
      console.error('Failed to create rotation:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateRotation = () => {
    if (selectedPlaylist) {
      createRotation(selectedPlaylist.id);
    }
  };

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Manage Rotations
      </Typography>
      
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
                    startIcon={<Add />}
                    onClick={() => {
                      setSelectedPlaylist(playlist);
                      setOpenDialog(true);
                    }}
                  >
                    Create Rotation
                  </Button>
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
              <Typography color="text.secondary">
                No active rotations yet. Create one by selecting a playlist above.
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create New Rotation</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Typography variant="h6" gutterBottom>
              {selectedPlaylist?.name}
            </Typography>
            <Typography color="text.secondary" paragraph>
              {selectedPlaylist?.description || 'No description'}
            </Typography>
            
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
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenDialog(false)}>Cancel</Button>
          <Button 
            onClick={handleCreateRotation} 
            variant="contained"
            disabled={loading}
          >
            {loading ? 'Creating...' : 'Create Rotation'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default Rotation;


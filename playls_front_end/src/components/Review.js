import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';
import {
  Container,
  Typography,
  Card,
  CardContent,
  CardMedia,
  Button,
  Box,
  Chip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Grid,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
} from '@mui/material';
import {
  ThumbUp,
  ThumbDown,
  SkipNext,
  MusicNote,
  PlayArrow,
  Pause,
} from '@mui/icons-material';

const Review = () => {
  const { user } = useAuth();
  const [songsToReview, setSongsToReview] = useState([]);
  const [currentSongIndex, setCurrentSongIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [openRecommendations, setOpenRecommendations] = useState(false);
  const [recommendations, setRecommendations] = useState([]);

  useEffect(() => {
    if (user) {
      fetchSongsToReview();
    }
  }, [user]);

  const fetchSongsToReview = async () => {
    try {
      // This would normally fetch from a specific rotation
      // For demo purposes, we'll use mock data
      const mockSongs = [
        {
          id: '1',
          name: 'Song Title 1',
          artist: 'Artist Name 1',
          album: 'Album Name 1',
          image: 'https://via.placeholder.com/300x300',
          addedAt: '2024-01-01T00:00:00Z',
          duration: 180000
        },
        {
          id: '2',
          name: 'Song Title 2',
          artist: 'Artist Name 2',
          album: 'Album Name 2',
          image: 'https://via.placeholder.com/300x300',
          addedAt: '2024-01-15T00:00:00Z',
          duration: 210000
        }
      ];
      setSongsToReview(mockSongs);
    } catch (error) {
      console.error('Failed to fetch songs to review:', error);
    }
  };

  const handleKeep = async () => {
    const currentSong = songsToReview[currentSongIndex];
    try {
      // API call to keep the song
      console.log('Keeping song:', currentSong.id);
      
      // Move to next song
      if (currentSongIndex < songsToReview.length - 1) {
        setCurrentSongIndex(currentSongIndex + 1);
      } else {
        // No more songs to review
        setSongsToReview([]);
      }
    } catch (error) {
      console.error('Failed to keep song:', error);
    }
  };

  const handleRemove = async () => {
    const currentSong = songsToReview[currentSongIndex];
    try {
      // API call to remove the song
      console.log('Removing song:', currentSong.id);
      
      // Move to next song
      if (currentSongIndex < songsToReview.length - 1) {
        setCurrentSongIndex(currentSongIndex + 1);
      } else {
        // No more songs to review
        setSongsToReview([]);
      }
    } catch (error) {
      console.error('Failed to remove song:', error);
    }
  };

  const handleSkip = () => {
    if (currentSongIndex < songsToReview.length - 1) {
      setCurrentSongIndex(currentSongIndex + 1);
    }
  };

  const fetchRecommendations = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`http://localhost:8000/recommendations?user_id=${user.id}`);
      setRecommendations(response.data.tracks || []);
      setOpenRecommendations(true);
    } catch (error) {
      console.error('Failed to fetch recommendations:', error);
    } finally {
      setLoading(false);
    }
  };

  const currentSong = songsToReview[currentSongIndex];

  if (songsToReview.length === 0) {
    return (
      <Container maxWidth="md" sx={{ mt: 8, textAlign: 'center' }}>
        <Typography variant="h4" gutterBottom>
          No Songs to Review
        </Typography>
        <Typography color="text.secondary" paragraph>
          All caught up! Your rotations are up to date.
        </Typography>
        <Button
          variant="contained"
          onClick={fetchRecommendations}
          disabled={loading}
        >
          {loading ? 'Loading...' : 'Find New Songs'}
        </Button>
      </Container>
    );
  }

  return (
    <Container maxWidth="sm" sx={{ mt: 4 }}>
      <Box sx={{ textAlign: 'center', mb: 4 }}>
        <Typography variant="h4" gutterBottom>
          Review Songs
        </Typography>
        <Typography color="text.secondary">
          {currentSongIndex + 1} of {songsToReview.length} songs
        </Typography>
      </Box>

      {currentSong && (
        <Card sx={{ mb: 4 }}>
          <CardMedia
            component="img"
            height="300"
            image={currentSong.image}
            alt={currentSong.name}
          />
          <CardContent>
            <Typography variant="h5" component="h2" gutterBottom>
              {currentSong.name}
            </Typography>
            <Typography color="text.secondary" gutterBottom>
              {currentSong.artist}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {currentSong.album}
            </Typography>
            <Box sx={{ mt: 2 }}>
              <Chip 
                label={`Added ${new Date(currentSong.addedAt).toLocaleDateString()}`}
                size="small"
              />
            </Box>
          </CardContent>
        </Card>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'center', gap: 2, mb: 4 }}>
        <Button
          variant="contained"
          color="error"
          size="large"
          startIcon={<ThumbDown />}
          onClick={handleRemove}
          sx={{ minWidth: 120 }}
        >
          Remove
        </Button>
        <Button
          variant="outlined"
          size="large"
          startIcon={<SkipNext />}
          onClick={handleSkip}
          sx={{ minWidth: 120 }}
        >
          Skip
        </Button>
        <Button
          variant="contained"
          color="success"
          size="large"
          startIcon={<ThumbUp />}
          onClick={handleKeep}
          sx={{ minWidth: 120 }}
        >
          Keep
        </Button>
      </Box>

      <Box sx={{ textAlign: 'center' }}>
        <Button
          variant="outlined"
          onClick={fetchRecommendations}
          disabled={loading}
        >
          {loading ? 'Loading...' : 'Find Replacement Songs'}
        </Button>
      </Box>

      <Dialog 
        open={openRecommendations} 
        onClose={() => setOpenRecommendations(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Recommended Songs</DialogTitle>
        <DialogContent>
          <List>
            {recommendations.map((track) => (
              <ListItem key={track.id}>
                <ListItemText
                  primary={track.name}
                  secondary={track.artists.map(a => a.name).join(', ')}
                />
                <ListItemSecondaryAction>
                  <Button
                    size="small"
                    onClick={() => {
                      // Add song to playlist
                      console.log('Adding song:', track.id);
                    }}
                  >
                    Add
                  </Button>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
          </List>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenRecommendations(false)}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default Review;


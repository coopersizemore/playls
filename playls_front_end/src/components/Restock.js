import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';
import {
  Container,
  Typography,
  Grid,
  Card,
  CardContent,
  CardActions,
  Button,
  TextField,
  Box,
  Chip,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  Tabs,
  Tab,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import {
  Search,
  MusicNote,
  Add,
  PlayArrow,
} from '@mui/icons-material';

const Restock = () => {
  const { user } = useAuth();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tabValue, setTabValue] = useState(0);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    
    try {
      setLoading(true);
      // This would normally search Spotify API
      // For demo, we'll use mock data
      const mockResults = [
        {
          id: '1',
          name: 'Search Result 1',
          artist: 'Artist 1',
          album: 'Album 1',
          image: 'https://via.placeholder.com/150x150'
        },
        {
          id: '2',
          name: 'Search Result 2',
          artist: 'Artist 2',
          album: 'Album 2',
          image: 'https://via.placeholder.com/150x150'
        }
      ];
      setSearchResults(mockResults);
    } catch (error) {
      console.error('Search failed:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchRecommendations = async (type) => {
    try {
      setLoading(true);
      const response = await axios.get(`http://localhost:8000/recommendations?user_id=${user.id}`);
      setRecommendations(response.data.tracks || []);
    } catch (error) {
      console.error('Failed to fetch recommendations:', error);
    } finally {
      setLoading(false);
    }
  };

  const addSongToPlaylist = async (songId) => {
    try {
      // API call to add song to playlist
      console.log('Adding song to playlist:', songId);
      // Show success message
    } catch (error) {
      console.error('Failed to add song:', error);
    }
  };

  const TabPanel = ({ children, value, index }) => (
    <div hidden={value !== index}>
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Find New Songs
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tabValue} onChange={(e, newValue) => setTabValue(newValue)}>
          <Tab label="Search" />
          <Tab label="Based on Your Taste" />
          <Tab label="Based on Artist" />
          <Tab label="Based on Song" />
          <Tab label="From History" />
          <Tab label="PlayLS Picks" />
        </Tabs>
      </Box>

      <TabPanel value={tabValue} index={0}>
        <Box sx={{ mb: 3 }}>
          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <TextField
              fullWidth
              label="Search for songs, artists, or albums"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            />
            <Button
              variant="contained"
              onClick={handleSearch}
              disabled={loading}
              startIcon={<Search />}
            >
              Search
            </Button>
          </Box>
        </Box>

        <Grid container spacing={2}>
          {searchResults.map((song) => (
            <Grid item xs={12} sm={6} md={4} key={song.id}>
              <Card>
                <CardContent>
                  <Box display="flex" alignItems="center" mb={2}>
                    <MusicNote color="primary" sx={{ mr: 1 }} />
                    <Box>
                      <Typography variant="h6">{song.name}</Typography>
                      <Typography color="text.secondary">{song.artist}</Typography>
                    </Box>
                  </Box>
                </CardContent>
                <CardActions>
                  <Button
                    size="small"
                    startIcon={<Add />}
                    onClick={() => addSongToPlaylist(song.id)}
                  >
                    Add to Playlist
                  </Button>
                  <Button
                    size="small"
                    startIcon={<PlayArrow />}
                  >
                    Preview
                  </Button>
                </CardActions>
              </Card>
            </Grid>
          ))}
        </Grid>
      </TabPanel>

      <TabPanel value={tabValue} index={1}>
        <Box sx={{ mb: 3 }}>
          <Button
            variant="contained"
            onClick={() => fetchRecommendations('taste')}
            disabled={loading}
          >
            {loading ? 'Loading...' : 'Get Recommendations'}
          </Button>
        </Box>

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
                  onClick={() => addSongToPlaylist(track.id)}
                >
                  Add
                </Button>
              </ListItemSecondaryAction>
            </ListItem>
          ))}
        </List>
      </TabPanel>

      <TabPanel value={tabValue} index={2}>
        <Box sx={{ mb: 3 }}>
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>Select Artist</InputLabel>
            <Select
              value=""
              onChange={() => {}}
            >
              <MenuItem value="artist1">Artist 1</MenuItem>
              <MenuItem value="artist2">Artist 2</MenuItem>
            </Select>
          </FormControl>
          <Button
            variant="contained"
            onClick={() => fetchRecommendations('artist')}
            disabled={loading}
          >
            {loading ? 'Loading...' : 'Get Similar Artists'}
          </Button>
        </Box>
      </TabPanel>

      <TabPanel value={tabValue} index={3}>
        <Box sx={{ mb: 3 }}>
          <TextField
            fullWidth
            label="Enter a song name"
            sx={{ mb: 2 }}
          />
          <Button
            variant="contained"
            onClick={() => fetchRecommendations('song')}
            disabled={loading}
          >
            {loading ? 'Loading...' : 'Get Similar Songs'}
          </Button>
        </Box>
      </TabPanel>

      <TabPanel value={tabValue} index={4}>
        <Typography variant="h6" gutterBottom>
          Songs from Your Rotation History
        </Typography>
        <Typography color="text.secondary">
          Songs you've previously removed from rotations
        </Typography>
        <Button
          variant="contained"
          sx={{ mt: 2 }}
          onClick={() => fetchRecommendations('history')}
          disabled={loading}
        >
          {loading ? 'Loading...' : 'View History'}
        </Button>
      </TabPanel>

      <TabPanel value={tabValue} index={5}>
        <Typography variant="h6" gutterBottom>
          PlayLS Daily Picks
        </Typography>
        <Typography color="text.secondary" paragraph>
          Curated songs to expand your musical taste
        </Typography>
        <Button
          variant="contained"
          onClick={() => fetchRecommendations('picks')}
          disabled={loading}
        >
          {loading ? 'Loading...' : 'Get Today\'s Picks'}
        </Button>
      </TabPanel>
    </Container>
  );
};

export default Restock;


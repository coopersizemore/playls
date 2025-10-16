import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import {
  Container,
  Typography,
  Card,
  CardContent,
  Box,
  Chip,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
  Tabs,
  Tab,
  Grid,
} from '@mui/material';
import {
  MusicNote,
  ThumbUp,
  ThumbDown,
  RestoreFromTrash,
} from '@mui/icons-material';

const History = () => {
  const { user } = useAuth();
  const [tabValue, setTabValue] = useState(0);
  const [history, setHistory] = useState({
    removed: [],
    added: [],
    kept: []
  });

  useEffect(() => {
    if (user) {
      fetchHistory();
    }
  }, [user]);

  const fetchHistory = async () => {
    try {
      // Mock data for demo
      const mockHistory = {
        removed: [
          {
            id: '1',
            name: 'Old Song 1',
            artist: 'Artist 1',
            removedAt: '2024-01-15T00:00:00Z',
            reason: 'user_removed'
          },
          {
            id: '2',
            name: 'Old Song 2',
            artist: 'Artist 2',
            removedAt: '2024-01-10T00:00:00Z',
            reason: 'user_removed'
          }
        ],
        added: [
          {
            id: '3',
            name: 'New Song 1',
            artist: 'Artist 3',
            addedAt: '2024-01-20T00:00:00Z',
            source: 'recommendation'
          },
          {
            id: '4',
            name: 'New Song 2',
            artist: 'Artist 4',
            addedAt: '2024-01-18T00:00:00Z',
            source: 'search'
          }
        ],
        kept: [
          {
            id: '5',
            name: 'Kept Song 1',
            artist: 'Artist 5',
            keptAt: '2024-01-12T00:00:00Z',
            daysInRotation: 30
          }
        ]
      };
      setHistory(mockHistory);
    } catch (error) {
      console.error('Failed to fetch history:', error);
    }
  };

  const restoreSong = async (songId) => {
    try {
      // API call to restore song
      console.log('Restoring song:', songId);
      // Update local state
    } catch (error) {
      console.error('Failed to restore song:', error);
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
        Rotation History
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tabValue} onChange={(e, newValue) => setTabValue(newValue)}>
          <Tab label="Removed Songs" />
          <Tab label="Added Songs" />
          <Tab label="Kept Songs" />
        </Tabs>
      </Box>

      <TabPanel value={tabValue} index={0}>
        <Typography variant="h6" gutterBottom>
          Songs You've Removed
        </Typography>
        <List>
          {history.removed.map((song) => (
            <Card key={song.id} sx={{ mb: 2 }}>
              <CardContent>
                <Box display="flex" alignItems="center" mb={1}>
                  <MusicNote color="primary" sx={{ mr: 1 }} />
                  <Box>
                    <Typography variant="h6">{song.name}</Typography>
                    <Typography color="text.secondary">{song.artist}</Typography>
                  </Box>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Chip 
                    label={`Removed ${new Date(song.removedAt).toLocaleDateString()}`}
                    size="small"
                    color="error"
                  />
                  <Chip 
                    label="User Removed"
                    size="small"
                    variant="outlined"
                  />
                </Box>
              </CardContent>
              <CardContent sx={{ pt: 0 }}>
                <IconButton
                  onClick={() => restoreSong(song.id)}
                  color="primary"
                >
                  <RestoreFromTrash />
                </IconButton>
              </CardContent>
            </Card>
          ))}
        </List>
      </TabPanel>

      <TabPanel value={tabValue} index={1}>
        <Typography variant="h6" gutterBottom>
          Songs You've Added
        </Typography>
        <List>
          {history.added.map((song) => (
            <Card key={song.id} sx={{ mb: 2 }}>
              <CardContent>
                <Box display="flex" alignItems="center" mb={1}>
                  <MusicNote color="primary" sx={{ mr: 1 }} />
                  <Box>
                    <Typography variant="h6">{song.name}</Typography>
                    <Typography color="text.secondary">{song.artist}</Typography>
                  </Box>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Chip 
                    label={`Added ${new Date(song.addedAt).toLocaleDateString()}`}
                    size="small"
                    color="success"
                  />
                  <Chip 
                    label={song.source}
                    size="small"
                    variant="outlined"
                  />
                </Box>
              </CardContent>
            </Card>
          ))}
        </List>
      </TabPanel>

      <TabPanel value={tabValue} index={2}>
        <Typography variant="h6" gutterBottom>
          Songs You've Kept
        </Typography>
        <List>
          {history.kept.map((song) => (
            <Card key={song.id} sx={{ mb: 2 }}>
              <CardContent>
                <Box display="flex" alignItems="center" mb={1}>
                  <MusicNote color="primary" sx={{ mr: 1 }} />
                  <Box>
                    <Typography variant="h6">{song.name}</Typography>
                    <Typography color="text.secondary">{song.artist}</Typography>
                  </Box>
                </Box>
                <Box display="flex" alignItems="center" gap={1}>
                  <Chip 
                    label={`Kept ${new Date(song.keptAt).toLocaleDateString()}`}
                    size="small"
                    color="success"
                  />
                  <Chip 
                    label={`${song.daysInRotation} days in rotation`}
                    size="small"
                    variant="outlined"
                  />
                </Box>
              </CardContent>
            </Card>
          ))}
        </List>
      </TabPanel>
    </Container>
  );
};

export default History;


import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import {
  Container,
  Typography,
  Button,
  Grid,
  Card,
  CardContent,
  CardActions,
  Box,
  AppBar,
  Toolbar,
} from '@mui/material';
import {
  MusicNote,
  RotateLeft,
  History,
  Settings,
  Add,
} from '@mui/icons-material';

const Home = () => {
  const navigate = useNavigate();
  const { user, login } = useAuth();

  if (!user) {
    return (
      <Box sx={{ flexGrow: 1 }}>
        <AppBar position="static">
          <Toolbar>
            <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
              PlayLS
            </Typography>
            <Button color="inherit" onClick={login}>
              Login with Spotify
            </Button>
          </Toolbar>
        </AppBar>
        <Container maxWidth="md" sx={{ mt: 8, textAlign: 'center' }}>
          <Typography variant="h2" component="h1" gutterBottom>
            Welcome to PlayLS
          </Typography>
          <Typography variant="h5" color="text.secondary" paragraph>
            Keep your Spotify playlists fresh by rotating songs in and out
          </Typography>
          <Button
            variant="contained"
            size="large"
            onClick={login}
            sx={{ mt: 4 }}
          >
            Get Started with Spotify
          </Button>
        </Container>
      </Box>
    );
  }

  return (
    <Box sx={{ flexGrow: 1 }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            PlayLS
          </Typography>
          <Button color="inherit" onClick={() => navigate('/settings')}>
            Settings
          </Button>
        </Toolbar>
      </AppBar>
      
      <Container maxWidth="lg" sx={{ mt: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Your Rotations
        </Typography>
        
        <Grid container spacing={3}>
          <Grid item xs={12} sm={6} md={4}>
            <Card>
              <CardContent>
                <Box display="flex" alignItems="center" mb={2}>
                  <MusicNote color="primary" sx={{ mr: 1 }} />
                  <Typography variant="h6">My Favorites</Typography>
                </Box>
                <Typography color="text.secondary">
                  Last rotated: 3 days ago
                </Typography>
                <Typography color="text.secondary">
                  5 songs ready for review
                </Typography>
              </CardContent>
              <CardActions>
                <Button size="small" onClick={() => navigate('/review')}>
                  Review Songs
                </Button>
                <Button size="small" onClick={() => navigate('/rotation')}>
                  Manage
                </Button>
              </CardActions>
            </Card>
          </Grid>
          
          <Grid item xs={12} sm={6} md={4}>
            <Card>
              <CardContent>
                <Box display="flex" alignItems="center" mb={2}>
                  <RotateLeft color="primary" sx={{ mr: 1 }} />
                  <Typography variant="h6">Workout Mix</Typography>
                </Box>
                <Typography color="text.secondary">
                  Last rotated: 1 week ago
                </Typography>
                <Typography color="text.secondary">
                  2 songs ready for review
                </Typography>
              </CardContent>
              <CardActions>
                <Button size="small" onClick={() => navigate('/review')}>
                  Review Songs
                </Button>
                <Button size="small" onClick={() => navigate('/rotation')}>
                  Manage
                </Button>
              </CardActions>
            </Card>
          </Grid>
          
          <Grid item xs={12} sm={6} md={4}>
            <Card sx={{ border: '2px dashed', borderColor: 'primary.main' }}>
              <CardContent>
                <Box display="flex" alignItems="center" mb={2}>
                  <Add color="primary" sx={{ mr: 1 }} />
                  <Typography variant="h6">Create New Rotation</Typography>
                </Box>
                <Typography color="text.secondary">
                  Connect a playlist to start rotating
                </Typography>
              </CardContent>
              <CardActions>
                <Button size="small" onClick={() => navigate('/rotation')}>
                  Create
                </Button>
              </CardActions>
            </Card>
          </Grid>
        </Grid>
        
        <Box mt={4}>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={6} md={3}>
              <Button
                variant="outlined"
                fullWidth
                startIcon={<RotateLeft />}
                onClick={() => navigate('/review')}
              >
                Review Songs
              </Button>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Button
                variant="outlined"
                fullWidth
                startIcon={<Add />}
                onClick={() => navigate('/restock')}
              >
                Find New Songs
              </Button>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Button
                variant="outlined"
                fullWidth
                startIcon={<History />}
                onClick={() => navigate('/history')}
              >
                History
              </Button>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Button
                variant="outlined"
                fullWidth
                startIcon={<Settings />}
                onClick={() => navigate('/settings')}
              >
                Settings
              </Button>
            </Grid>
          </Grid>
        </Box>
      </Container>
    </Box>
  );
};

export default Home;


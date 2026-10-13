import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import {
  Container,
  Typography,
  Button,
  Box,
  Alert,
} from '@mui/material';

const Login = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user, login } = useAuth();
  // The backend finishes the Spotify flow itself and redirects to / on success,
  // or back here with ?error=auth_failed
  const error = searchParams.get('error') ? 'Login was cancelled or failed' : null;

  useEffect(() => {
    if (user) {
      navigate('/');
    }
  }, [user, navigate]);

  if (user) {
    return null;
  }

  return (
    <Container maxWidth="sm" sx={{ mt: 8 }}>
      <Box sx={{ textAlign: 'center' }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Welcome to PlayLS
        </Typography>
        <Typography variant="h6" color="text.secondary" paragraph>
          Connect your Spotify account to start rotating your playlists
        </Typography>
        
        {error && (
          <Alert severity="error" sx={{ mb: 3 }}>
            {error}
          </Alert>
        )}
        
        <Button
          variant="contained"
          size="large"
          onClick={login}
          sx={{ mt: 2 }}
        >
          Login with Spotify
        </Button>
        
        <Typography variant="body2" color="text.secondary" sx={{ mt: 4 }}>
          By logging in, you agree to let PlayLS access your Spotify playlists
          to help you keep them fresh and up-to-date.
        </Typography>
      </Box>
    </Container>
  );
};

export default Login;


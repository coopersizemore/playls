import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import {
  Container,
  Typography,
  Button,
  Box,
  CircularProgress,
  Alert,
} from '@mui/material';

const Login = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user, login, handleCallback } = useAuth();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);

  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const error = searchParams.get('error');

    if (error) {
      setError('Login was cancelled or failed');
      return;
    }

    if (code && state) {
      setLoading(true);
      handleCallback(code, state).then((success) => {
        if (success) {
          navigate('/');
        } else {
          setError('Login failed. Please try again.');
        }
        setLoading(false);
      });
    }
  }, [searchParams, handleCallback, navigate]);

  if (user) {
    navigate('/');
    return null;
  }

  if (loading) {
    return (
      <Container maxWidth="sm" sx={{ mt: 8, textAlign: 'center' }}>
        <CircularProgress />
        <Typography variant="h6" sx={{ mt: 2 }}>
          Logging you in...
        </Typography>
      </Container>
    );
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


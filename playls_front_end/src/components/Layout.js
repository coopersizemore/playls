import React from 'react';
import { Link as RouterLink, Navigate } from 'react-router-dom';
import { AppBar, Avatar, Box, Button, Container, Toolbar, Typography } from '@mui/material';
import { QueueMusic } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';

// App chrome for signed-in pages
export const Layout = ({ children, maxWidth = 'lg' }) => {
  const { user } = useAuth();
  return (
  <Box sx={{ flexGrow: 1, pb: 6 }}>
    <AppBar position="static">
      <Toolbar>
        <Typography
          variant="h6"
          component={RouterLink}
          to="/"
          sx={{ flexGrow: 1, color: 'inherit', textDecoration: 'none' }}
        >
          PlayLS
        </Typography>
        {user?.is_admin && (
          <Button color="inherit" component={RouterLink} to="/admin/picks">
            Curate
          </Button>
        )}
        <Button color="inherit" component={RouterLink} to="/settings">
          Settings
        </Button>
      </Toolbar>
    </AppBar>
    <Container maxWidth={maxWidth} sx={{ mt: 4 }}>
      {children}
    </Container>
  </Box>
  );
};

// A rotation's playlist cover (falls back to an icon, e.g. for a new empty playlist)
export const PlaylistCover = ({ rotation, size = 48 }) => (
  <Avatar
    variant="rounded"
    src={rotation?.image_url || undefined}
    alt={rotation ? `${rotation.name} cover` : ''}
    sx={{ width: size, height: size, bgcolor: 'action.hover', color: 'primary.main' }}
  >
    <QueueMusic sx={{ fontSize: size * 0.55 }} />
  </Avatar>
);

// Page title with the rotation's cover
export const RotationHeader = ({ rotation, title, centered = false }) => (
  <Box display="flex" alignItems="center" justifyContent={centered ? 'center' : 'flex-start'} gap={2} mb={1}>
    <PlaylistCover rotation={rotation} size={56} />
    <Typography variant="h4" component="h1" sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>{title}</Typography>
  </Box>
);

// Spotify's embedded player for one track
export const SpotifyEmbed = ({ trackId, title }) => (
  <Box
    component="iframe"
    key={trackId}
    title={`Spotify player: ${title}`}
    src={`https://open.spotify.com/embed/track/${encodeURIComponent(trackId)}`}
    allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
    loading="lazy"
    sx={{ width: '100%', height: 152, border: 0, display: 'block' }}
  />
);

// Signed-out visitors go to the landing page
export const RequireAuth = ({ children }) => {
  const { user } = useAuth();
  return user ? children : <Navigate to="/" replace />;
};

export const formatDate = (iso) =>
  // API timestamps are naive UTC
  iso ? new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleDateString() : '';

export const relativeDays = (iso) => {
  if (!iso) return '';
  const ms = new Date(iso.endsWith('Z') ? iso : `${iso}Z`) - new Date();
  const days = Math.round(ms / 86400000);
  if (days === 0) return 'today';
  return days > 0 ? `in ${days} day${days === 1 ? '' : 's'}` : `${-days} day${days === -1 ? '' : 's'} ago`;
};

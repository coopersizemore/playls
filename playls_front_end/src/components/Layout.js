import React, { useState } from 'react';
import { Link as RouterLink, Navigate, useNavigate } from 'react-router-dom';
import {
  Avatar,
  Box,
  Container,
  Divider,
  IconButton,
  ListItemIcon,
  Menu,
  MenuItem,
  Switch,
  Typography,
} from '@mui/material';
import { ArrowBack, DarkMode, HelpOutline, Home, Logout, Menu as MenuIcon, QueueMusic, Settings, Star } from '@mui/icons-material';
import { useAuth } from '../contexts/AuthContext';
import { useColorMode } from '../colorMode';
import { HelpDialog } from './Help';

// The PlayLS wordmark: "Play" in the text color, "LS" in the brand green
export const Wordmark = () => (
  <>Play<Box component="span" sx={{ color: 'primary.main' }}>LS</Box></>
);

// Minimal top bar from the wireframes: back arrow (or the PlayLS wordmark on top-level
// pages) on the left, a ☰ menu on the right.
const TopBar = ({ back }) => {
  const { user, logout } = useAuth();
  const { mode, toggle } = useColorMode();
  const navigate = useNavigate();
  const [anchor, setAnchor] = useState(null);
  const [help, setHelp] = useState(false);
  const go = (to) => { setAnchor(null); navigate(to); };

  return (
    <Box display="flex" alignItems="center" justifyContent="space-between" py={1.5}>
      {back ? (
        <IconButton aria-label="Back" component={RouterLink} to={back} edge="start" sx={{ color: 'text.primary' }}>
          <ArrowBack />
        </IconButton>
      ) : (
        <Typography component={RouterLink} to="/" variant="h6"
          sx={{ color: 'text.primary', textDecoration: 'none', fontWeight: 700, letterSpacing: '0.04em' }}>
          <Wordmark />
        </Typography>
      )}
      <Box display="flex" alignItems="center">
        <IconButton aria-label="How PlayLS works" onClick={() => setHelp(true)} sx={{ color: 'text.primary' }}>
          <HelpOutline />
        </IconButton>
        <IconButton aria-label="Menu" onClick={(e) => setAnchor(e.currentTarget)} edge="end" sx={{ color: 'text.primary' }}>
          <MenuIcon />
        </IconButton>
      </Box>
      <HelpDialog open={help} onClose={() => setHelp(false)} userId={user?.id} />
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
        <MenuItem onClick={() => go('/')}><ListItemIcon><Home fontSize="small" /></ListItemIcon>Home</MenuItem>
        <MenuItem onClick={() => go('/settings')}><ListItemIcon><Settings fontSize="small" /></ListItemIcon>Settings</MenuItem>
        {user?.is_admin && (
          <MenuItem onClick={() => go('/admin/picks')}><ListItemIcon><Star fontSize="small" /></ListItemIcon>Curate picks</MenuItem>
        )}
        <Divider />
        {/* Stays open so the switch's effect is visible */}
        <MenuItem onClick={toggle}>
          <ListItemIcon><DarkMode fontSize="small" /></ListItemIcon>
          Dark mode
          <Switch size="small" edge="end" checked={mode === 'dark'} tabIndex={-1} sx={{ ml: 2, pointerEvents: 'none' }}
            inputProps={{ 'aria-label': 'Dark mode' }} />
        </MenuItem>
        <Divider />
        <MenuItem onClick={async () => { setAnchor(null); await logout(); navigate('/'); }}>
          <ListItemIcon><Logout fontSize="small" /></ListItemIcon>Log out
        </MenuItem>
      </Menu>
    </Box>
  );
};

// Page chrome for signed-in pages. `back`: where the back arrow goes (omit on top-level pages).
export const Layout = ({ children, maxWidth = 'lg', back }) => (
  <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
    <Container maxWidth={maxWidth} sx={{ pb: 6 }}>
      <TopBar back={back} />
      {children}
    </Container>
  </Box>
);

// A rotation's playlist cover (falls back to an icon, e.g. for a new empty playlist)
export const PlaylistCover = ({ rotation, size = 48, radius = 1.5, shadow = false }) => (
  <Avatar
    variant="rounded"
    src={rotation?.image_url || undefined}
    alt={rotation ? `${rotation.name} cover` : ''}
    sx={{
      width: size, height: size, borderRadius: radius, bgcolor: 'placeholder.main', color: 'text.secondary',
      boxShadow: shadow ? '0 4px 10px rgba(0,0,0,0.25)' : 'none',
    }}
  >
    <QueueMusic sx={{ fontSize: size * 0.45 }} />
  </Avatar>
);

// Square album art with a placeholder, as in the wireframes
export const AlbumArt = ({ src, alt, size = '100%', radius = 3 }) => (
  <Box sx={{
    width: size, aspectRatio: '1 / 1', borderRadius: radius, overflow: 'hidden', bgcolor: 'placeholder.main',
    boxShadow: '0 4px 10px rgba(0,0,0,0.25)', display: 'flex', alignItems: 'center', justifyContent: 'center',
  }}>
    {src ? (
      <Box component="img" src={src} alt={alt} draggable={false}
        sx={{ width: '100%', height: '100%', objectFit: 'cover', userSelect: 'none', pointerEvents: 'none' }} />
    ) : (
      <QueueMusic sx={{ fontSize: 64, color: 'text.secondary' }} />
    )}
  </Box>
);

// Small title row with the rotation's cover (Restock and similar pages)
export const RotationHeader = ({ rotation, title, centered = false }) => (
  <Box display="flex" alignItems="center" justifyContent={centered ? 'center' : 'flex-start'} gap={2} mb={1}>
    <PlaylistCover rotation={rotation} size={56} />
    <Typography variant="h5" component="h1" sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>{title}</Typography>
  </Box>
);

// Spotify's embedded player for one track (compact = the 80px single-row player)
export const SpotifyEmbed = ({ trackId, title, compact = false }) => (
  <Box
    component="iframe"
    key={trackId}
    title={`Spotify player: ${title}`}
    src={`https://open.spotify.com/embed/track/${encodeURIComponent(trackId)}`}
    allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
    loading="lazy"
    // Spotify's player has 12px corners; a bigger radius (theme units multiply by 12) clips it
    sx={{ width: '100%', height: compact ? 80 : 152, border: 0, display: 'block', borderRadius: '12px' }}
  />
);

// Signed-out visitors go to the landing page
export const RequireAuth = ({ children }) => {
  const { user } = useAuth();
  return user ? children : <Navigate to="/" replace />;
};

export const parseUtc = (iso) => new Date(iso.endsWith('Z') ? iso : `${iso}Z`);

export const formatDate = (iso) =>
  // API timestamps are naive UTC
  iso ? parseUtc(iso).toLocaleDateString() : '';

export const relativeDays = (iso) => {
  if (!iso) return '';
  const days = Math.round((parseUtc(iso) - new Date()) / 86400000);
  if (days === 0) return 'today';
  return days > 0 ? `in ${days} day${days === 1 ? '' : 's'}` : `${-days} day${days === -1 ? '' : 's'} ago`;
};

// Whole days since a timestamp (null if unknown)
export const daysSince = (iso) => (iso ? Math.max(0, Math.floor((new Date() - parseUtc(iso)) / 86400000)) : null);

// "6h 4m" style total length
export const formatDuration = (ms) => {
  const minutes = Math.round((ms || 0) / 60000);
  const h = Math.floor(minutes / 60);
  return h ? `${h}h ${minutes % 60}m` : `${minutes}m`;
};

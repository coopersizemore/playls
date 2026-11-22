import React from 'react';
import { Link as RouterLink, Navigate } from 'react-router-dom';
import { AppBar, Box, Button, Container, Toolbar, Typography } from '@mui/material';
import { useAuth } from '../contexts/AuthContext';

// App chrome for signed-in pages
export const Layout = ({ children, maxWidth = 'lg' }) => (
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

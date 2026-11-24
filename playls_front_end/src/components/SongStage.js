import React from 'react';
import { Box, Card, Typography } from '@mui/material';

// Album art plus a details column: stacked on phones, side by side from `md` up. The art is
// sized from the viewport height so the card and its controls fit on one screen.
// reserve: { xs, md } px of everything else on screen (top bar, header, controls) in each
// layout; the art gets the rest, within the min / max below.
const MIN_ART = 160;
const MIN_ART_MD = 260;
const MAX_ART_MD = 440;

const SongStage = ({ art, children, reserve }) => (
  <Box sx={{
    display: { md: 'grid' }, gridTemplateColumns: { md: 'auto minmax(0, 1fr)' }, columnGap: 4, alignItems: 'center',
  }}>
    <Box sx={{
      mx: 'auto',
      width: {
        xs: `min(100%, max(${MIN_ART}px, calc(100svh - ${reserve.xs}px)))`,
        md: `clamp(${MIN_ART_MD}px, calc(100svh - ${reserve.md}px), ${MAX_ART_MD}px)`,
      },
    }}>
      {art}
    </Box>
    <Box sx={{ minWidth: 0, mt: { xs: 1.5, md: 0 } }}>{children}</Box>
  </Box>
);

// The card that groups a song's details, player and decision buttons
export const DetailsPanel = ({ children }) => (
  <Card component="section" sx={{ p: { xs: 1.5, sm: 2 } }}>{children}</Card>
);

// A titled section inside the panel, spaced from the one above
export const PanelSection = ({ children, mt = 1.5 }) => <Box mt={mt}>{children}</Box>;

// Back / Skip and other secondary moves: a quiet row under a divider at the panel's foot
export const NavRow = ({ children }) => (
  <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}
    mt={1.5} pt={1} sx={{ borderTop: 1, borderColor: 'divider', '& .MuiButton-root': { color: 'text.secondary' } }}>
    {children}
  </Box>
);

// Muted help text under the panel
export const PanelNote = ({ children }) => (
  <Typography variant="caption" color="text.secondary" component="p" textAlign="center"
    sx={{ mt: 1, mb: 0, px: 1, lineHeight: 1.45 }}>
    {children}
  </Typography>
);

export default SongStage;

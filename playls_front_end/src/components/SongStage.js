import React from 'react';
import { Box } from '@mui/material';

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

export default SongStage;

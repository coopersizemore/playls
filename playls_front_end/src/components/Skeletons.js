import React from 'react';
import { Box, Card, CardActions, CardContent, Grid, Skeleton } from '@mui/material';
import SongStage from './SongStage';

// Loading placeholders shaped like the content they stand in for, so the page doesn't
// jump when data arrives. Wave animation; colors follow the light/dark theme.

const W = { animation: 'wave' };

// Home: a grid of rotation cards
export const RotationCardsSkeleton = ({ count = 3 }) => (
  <Grid container spacing={3} aria-busy="true" aria-label="Loading rotations">
    {Array.from({ length: count }).map((_, i) => (
      <Grid key={i} size={{ xs: 12, sm: 6, md: 4 }}>
        <Card>
          <CardContent>
            <Box display="flex" alignItems="center" gap={2} mb={1.5}>
              <Skeleton {...W} variant="rounded" width={72} height={72} sx={{ borderRadius: 2, flexShrink: 0 }} />
              <Box flexGrow={1}>
                <Skeleton {...W} width="70%" height={30} />
                <Skeleton {...W} width="50%" />
              </Box>
            </Box>
            <Skeleton {...W} width="80%" />
            <Skeleton {...W} width="45%" />
          </CardContent>
          <CardActions sx={{ px: 2, pb: 2, gap: 1 }}>
            <Skeleton {...W} variant="rounded" width={104} height={36} sx={{ borderRadius: 2.5 }} />
            <Skeleton {...W} variant="rounded" width={104} height={36} sx={{ borderRadius: 2.5 }} />
          </CardActions>
        </Card>
      </Grid>
    ))}
  </Grid>
);

// The green pill rows in a rotation's song list
export const SongRowsSkeleton = ({ count = 6 }) => (
  <Box display="flex" flexDirection="column" gap={1.5} aria-busy="true" aria-label="Loading songs">
    {Array.from({ length: count }).map((_, i) => (
      <Box key={i} display="flex" alignItems="center" gap={2} px={1.5} py={1.25}
        sx={{ borderRadius: 999, bgcolor: 'action.hover' }}>
        <Skeleton {...W} variant="rounded" width={52} height={52} sx={{ borderRadius: 2.5, flexShrink: 0 }} />
        <Box flexGrow={1}>
          <Skeleton {...W} width={`${55 + ((i * 17) % 30)}%`} />
          <Skeleton {...W} width={`${30 + ((i * 11) % 25)}%`} />
        </Box>
      </Box>
    ))}
  </Box>
);

// Rotation page: cover, name, stats, the 2x2 tiles, then the songs panel
export const RotationPageSkeleton = () => (
  <Box aria-busy="true" aria-label="Loading rotation">
    <Box display="flex" flexDirection="column" alignItems="center">
      <Skeleton {...W} variant="rounded" width={220} height={220} sx={{ borderRadius: 3 }} />
      <Skeleton {...W} width={220} height={40} sx={{ mt: 2 }} />
    </Box>
    <Box display="flex" justifyContent="space-between" mt={2} mb={3}>
      <Skeleton {...W} width={80} />
      <Skeleton {...W} width={150} />
      <Skeleton {...W} width={50} />
    </Box>
    <Box display="grid" gridTemplateColumns="1fr 1fr" gap={2.5} mb={4}>
      {[0, 1, 2, 3].map((i) => <Skeleton key={i} {...W} variant="rounded" height={72} sx={{ borderRadius: 2 }} />)}
    </Box>
    <Box sx={{ bgcolor: 'surface.main', borderRadius: 4, p: { xs: 1.5, sm: 2.5 } }}>
      <Skeleton {...W} height={44} sx={{ mb: 2 }} />
      <SongRowsSkeleton count={4} />
    </Box>
  </Box>
);

// Review / restock card: big art, title, artist, stat, player
export const SongCardSkeleton = ({ reserve, stat = true }) => (
  <Box aria-busy="true" aria-label="Loading songs">
    <SongStage reserve={reserve}
      art={<Skeleton {...W} variant="rounded" sx={{ width: '100%', height: 'auto', aspectRatio: '1 / 1', borderRadius: 3 }} />}>
      <Box display="flex" alignItems="center" gap={2}>
        <Box flexGrow={1}>
          <Skeleton {...W} width="70%" height={28} />
          <Skeleton {...W} width="45%" />
        </Box>
        {stat && <Skeleton {...W} width={64} height={44} />}
      </Box>
      <Skeleton {...W} variant="rounded" height={80} sx={{ mt: 1.5, borderRadius: 3 }} />
      <Skeleton {...W} variant="rounded" height={40} sx={{ mt: 1.5, borderRadius: 2 }} />
    </SongStage>
  </Box>
);

// Review page: progress + tally above the card
export const ReviewSkeleton = ({ reserve }) => (
  <Box>
    <Box display="flex" justifyContent="space-between"><Skeleton {...W} width={140} /><Skeleton {...W} width={60} /></Box>
    <Skeleton {...W} variant="rounded" height={6} sx={{ mt: 0.75, mb: 1, borderRadius: 3 }} />
    <Box display="flex" justifyContent="center" gap={1} mb={1.5}>
      {[0, 1, 2].map((i) => <Skeleton key={i} {...W} variant="rounded" width={84} height={24} sx={{ borderRadius: 4 }} />)}
    </Box>
    <SongCardSkeleton reserve={reserve} />
  </Box>
);

// Generic avatar + two lines list (History, picks, playlists in dialogs, blocked songs)
export const ListSkeleton = ({ count = 5, avatar = 40, dense = false }) => (
  <Box aria-busy="true" aria-label="Loading">
    {Array.from({ length: count }).map((_, i) => (
      <Box key={i} display="flex" alignItems="center" gap={2} py={dense ? 0.75 : 1.25}>
        <Skeleton {...W} variant="rounded" width={avatar} height={avatar} sx={{ flexShrink: 0 }} />
        <Box flexGrow={1}>
          <Skeleton {...W} width={`${50 + ((i * 13) % 35)}%`} />
          <Skeleton {...W} width={`${25 + ((i * 7) % 30)}%`} />
        </Box>
      </Box>
    ))}
  </Box>
);

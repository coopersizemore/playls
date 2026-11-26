import React from 'react';
import { Box, Chip } from '@mui/material';
import { Headphones } from '@mui/icons-material';
import { relativeDays } from './Layout';

// Listening history wording, shared by Review, the song list, Restock and History.
// The server sends `listening` only when there's something to say (see ListeningOut).

const RANGE_WORDS = {
  short_term: 'this month',
  medium_term: 'the last 6 months',
  long_term: 'this year',
};

// "3 weeks", "60 days"
export const windowLabel = (days) => (days % 7 === 0 ? `${days / 7} weeks` : `${days} days`);

// "2 weeks" for a span in hours (History: "N plays in the 2 weeks before")
export const hoursLabel = (hours) => {
  const days = Math.round(hours / 24);
  if (days < 1) return `${hours} hours`;
  if (days % 7 === 0) return days === 7 ? 'week' : `${days / 7} weeks`;
  return days === 1 ? 'day' : `${days} days`;
};

const bestRank = (topRank = {}) => {
  for (const range of ['short_term', 'medium_term', 'long_term']) {
    if (topRank[range] != null) return { range, rank: topRank[range] };
  }
  return null;
};

export const topLabel = (topRank) => {
  const best = bestRank(topRank);
  return best ? `#${best.rank + 1} in your top songs ${RANGE_WORDS[best.range]}` : null;
};

// Chips for a song's listening, most positive first. "Few plays lately" only comes when the
// server is confident, and stays quiet (outlined, no color).
export const listeningBadges = (listening) => {
  if (!listening) return [];
  const badges = [];
  const top = topLabel(listening.top_rank);
  if (listening.held) badges.push({ label: 'Held back: you play this a lot', color: 'primary' });
  // A top-songs rank already says "a lot"; the plain chip is for songs heavy by plays alone
  else if (listening.heavy && !top) badges.push({ label: 'You play this a lot', color: 'primary', variant: 'filled' });
  if (top) badges.push({ label: top, color: 'primary', variant: listening.heavy ? 'filled' : 'outlined' });
  if (listening.plays > 0) {
    const here = listening.plays_here !== listening.plays ? ` (${listening.plays_here} here)` : '';
    badges.push({ label: `Played ${listening.plays}× in ${windowLabel(listening.window_days)}${here}` });
    if (listening.last_played_at) badges.push({ label: `Last played ${relativeDays(listening.last_played_at)}` });
  }
  if (listening.few_plays) badges.push({ label: 'Few plays lately', quiet: true });
  if (listening.starts >= 3) badges.push({ label: `Skipped ${listening.skips} of ${listening.starts} starts`, quiet: true });
  return badges;
};

export const BadgeRow = ({ badges, sx }) => (badges.length > 0 ? (
  <Box display="flex" gap={1} mt={1} flexWrap="wrap" sx={sx}>
    {badges.map((b) => (
      <Chip key={b.label} size="small" color={b.color || 'default'} variant={b.variant || 'outlined'} label={b.label}
        icon={b.icon} sx={b.quiet ? { color: 'text.secondary', borderStyle: 'dashed' } : undefined} />
    ))}
  </Box>
) : null);

// Compact play count for list rows ("6 plays")
export const playsText = (listening) => {
  if (!listening) return null;
  if (listening.plays > 0) return `${listening.plays} play${listening.plays === 1 ? '' : 's'}`;
  return null;
};

export const PlaysIcon = Headphones;

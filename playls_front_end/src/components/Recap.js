import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Avatar,
  Box,
  Card,
  CardContent,
  Grid,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  MenuItem,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useTheme,
} from '@mui/material';
import { MusicNote } from '@mui/icons-material';
import { BarChart } from '@mui/x-charts/BarChart';
import { api, errorMessage } from '../api';
import { Layout } from './Layout';

// A rotation's month: listening (from the listening history) and turnover. Lazy-loaded from
// App.js so the charting library only loads here and on the admin dashboard.

// Single series: the validated slot-1 blue from AdminStats (dataviz reference palette)
const BAR = { light: '#2a78d6', dark: '#3987e5' };
const SOURCE_LABELS = {
  bring_back: 'Bring back', picks: 'PlayLS picks', suggested: 'For you', search: 'Search', rediscover: 'Rediscover',
};

const monthLabel = (ym) => {
  const [y, m] = ym.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
};
const dayNumber = (iso) => Number(iso.split('-')[2]);
const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;

const Stat = ({ label, value, hint }) => (
  <Card sx={{ height: '100%' }}>
    <CardContent sx={{ py: 2, '&:last-child': { pb: 2 } }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Typography sx={{ fontSize: '1.7rem', fontWeight: 600, lineHeight: 1.2, my: 0.5 }}>{value}</Typography>
      <Typography variant="caption" color="text.secondary">{hint || ' '}</Typography>
    </CardContent>
  </Card>
);

const SongList = ({ songs, detail }) => (
  <List dense disablePadding>
    {songs.map((s) => (
      <ListItem key={s.track_id} disableGutters>
        <ListItemAvatar>
          <Avatar variant="rounded" src={s.image_url || undefined}><MusicNote /></Avatar>
        </ListItemAvatar>
        <ListItemText sx={{ minWidth: 0 }} primary={s.title} secondary={s.artists || ' '}
          slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }} />
        <Typography variant="body2" sx={{ ml: 1, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
          {detail(s)}
        </Typography>
      </ListItem>
    ))}
  </List>
);

const Section = ({ title, children, action }) => (
  <Card sx={{ mt: 2 }}>
    <CardContent>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} mb={1}>
        <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>{title}</Typography>
        {action}
      </Box>
      {children}
    </CardContent>
  </Card>
);

// Plays from the playlist per day, with a table view of the same numbers
const DailyPlays = ({ days }) => {
  const theme = useTheme();
  const [view, setView] = useState('chart');
  const mode = theme.palette.mode === 'dark' ? 'dark' : 'light';
  const toggle = (
    <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}
      aria-label="Daily plays: chart or table">
      <ToggleButton value="chart">Chart</ToggleButton>
      <ToggleButton value="table">Table</ToggleButton>
    </ToggleButtonGroup>
  );
  return (
    <Section title="Plays from this playlist each day" action={toggle}>
      {view === 'chart' ? (
        <BarChart height={220} borderRadius={4} hideLegend grid={{ horizontal: true }}
          margin={{ left: 0, right: 8, top: 16, bottom: 4 }}
          xAxis={[{ scaleType: 'band', data: days.map((d) => dayNumber(d.date)), tickLabelInterval: (_, i) => i % 5 === 0 }]}
          yAxis={[{ tickMinStep: 1, width: 32 }]}
          series={[{ data: days.map((d) => d.plays_here), label: 'Plays', color: BAR[mode] }]} />
      ) : (
        <Box sx={{ maxHeight: 280, overflowY: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead><TableRow><TableCell>Day</TableCell><TableCell align="right">Plays</TableCell></TableRow></TableHead>
            <TableBody>
              {days.map((d) => (
                <TableRow key={d.date}>
                  <TableCell>{d.date}</TableCell>
                  <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>{d.plays_here}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Section>
  );
};

const RecapSkeleton = () => (
  <>
    <Grid container spacing={2}>
      {[0, 1, 2, 3].map((i) => (
        <Grid key={i} size={6}><Skeleton variant="rounded" height={96} /></Grid>
      ))}
    </Grid>
    <Skeleton variant="rounded" height={260} sx={{ mt: 2 }} />
    <Skeleton variant="rounded" height={200} sx={{ mt: 2 }} />
  </>
);

const Recap = () => {
  const { rotationId } = useParams();
  const [rotation, setRotation] = useState(null);
  const [month, setMonth] = useState(null);
  const [recap, setRecap] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.rotation(rotationId, { sync: false }).then(setRotation).catch(() => {});
  }, [rotationId]);

  useEffect(() => {
    let cancelled = false;
    setRecap(null);
    setError('');
    api.recap(rotationId, month)
      .then((r) => { if (!cancelled) setRecap(r); })
      .catch((e) => { if (!cancelled) setError(errorMessage(e, 'Failed to load the recap.')); });
    return () => { cancelled = true; };
  }, [rotationId, month]);

  const turnover = recap ? [
    { label: 'Added', value: recap.added,
      hint: Object.entries(recap.added_by_source).map(([s, n]) => `${SOURCE_LABELS[s] || s} ${n}`).join(' · ') },
    { label: 'Kept', value: recap.kept },
    { label: 'Super kept', value: recap.super_kept },
    { label: 'Removed', value: recap.removed },
    ...(rotation?.kind === 'auto' ? [{ label: 'Rotated out', value: recap.rotated_out }] : []),
  ] : [];

  return (
    <Layout maxWidth="sm" back={`/rotation/${rotationId}`}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={2}>
        <Box minWidth={0}>
          <Typography variant="h5" component="h1" noWrap>Recap</Typography>
          <Typography variant="body2" color="text.secondary" noWrap>{rotation?.name || ' '}</Typography>
        </Box>
        {recap && (
          <TextField select size="small" label="Month" value={recap.month} sx={{ minWidth: 180 }}
            onChange={(e) => setMonth(e.target.value)}>
            {recap.months.map((m) => <MenuItem key={m} value={m}>{monthLabel(m)}</MenuItem>)}
          </TextField>
        )}
      </Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {!recap && !error && <RecapSkeleton />}
      {recap && (
        <>
          {!recap.listening_enabled ? (
            <Alert severity="info" sx={{ mb: 2 }}>Listening history is off, so this recap only shows reviews and restocks.</Alert>
          ) : !recap.covered && (
            <Alert severity="info" sx={{ mb: 2 }}>PlayLS hadn't started saving your plays yet in {monthLabel(recap.month)}.</Alert>
          )}
          {recap.listening_enabled && recap.covered && (
            <Grid container spacing={2}>
              <Grid size={6}><Stat label="Plays from this playlist" value={recap.plays_here.toLocaleString()} /></Grid>
              <Grid size={6}>
                <Stat label="Its songs played elsewhere" value={recap.plays_elsewhere.toLocaleString()} hint="Albums, other playlists…" />
              </Grid>
              <Grid size={6}>
                <Stat label="Songs played" value={recap.songs_played.toLocaleString()} hint={`of ${plural(recap.song_count, 'song')}`} />
              </Grid>
              <Grid size={6}>
                <Stat label="New songs played" value={recap.added ? `${recap.adds_played} of ${recap.added}` : '—'}
                  hint={recap.added ? 'added this month, played since' : 'none added this month'} />
              </Grid>
            </Grid>
          )}
          {recap.listening_enabled && recap.covered && recap.days.length > 0 && <DailyPlays days={recap.days} />}
          {recap.top_songs.length > 0 && (
            <Section title="Most played">
              <SongList songs={recap.top_songs} detail={(s) => `${s.plays}×`} />
            </Section>
          )}
          <Section title="Turnover">
            <Table size="small">
              <TableBody>
                {turnover.map((t) => (
                  <TableRow key={t.label}>
                    <TableCell sx={{ border: 0, pl: 0 }}>
                      {t.label}
                      {t.hint && <Typography variant="caption" color="text.secondary" display="block">{t.hint}</Typography>}
                    </TableCell>
                    <TableCell align="right" sx={{ border: 0, pr: 0, fontVariantNumeric: 'tabular-nums' }}>{t.value}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
          {recap.most_kept.length > 0 && (
            <Section title="Kept the most">
              <SongList songs={recap.most_kept} detail={(s) => `kept ${s.times}×`} />
            </Section>
          )}
          {recap.starts > 0 && (
            <Typography variant="body2" color="text.secondary" mt={2}>
              From your imported Spotify history: {recap.skips} of {plural(recap.starts, 'start')} of these songs were skipped.
            </Typography>
          )}
        </>
      )}
    </Layout>
  );
};

export default Recap;

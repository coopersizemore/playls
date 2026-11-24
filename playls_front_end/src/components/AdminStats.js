import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  Grid,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material';
import { BarChart } from '@mui/x-charts/BarChart';
import { LineChart } from '@mui/x-charts/LineChart';
import { api, errorMessage } from '../api';
import { Layout } from './Layout';

// Admin-only monitoring dashboard (docs/MONITORING_PLAN.md). Lazy-loaded from App.js, so regular
// users never download it or the charting library. Usage numbers come only from users who opted
// in; app health has no user attached. Everything here is an aggregate.

// ---------- palette (validated: dataviz reference categorical slots 1-4, both modes) ----------
const SERIES = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500'],
};
// Sequential blue for the heatmap: first step is "none", then light -> dark (dark mode: dim -> bright)
const HEAT = {
  light: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'],
  dark: ['#104281', '#184f95', '#1c5cab', '#2a78d6', '#3987e5', '#6da7ec', '#9ec5f4'],
};

const RANGES = [7, 30, 90, 180];
const KINDS = [{ value: 'all', label: 'All rotations' }, { value: 'manual', label: 'Manual' }, { value: 'auto', label: 'Auto' }];
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const ACTIONS = [
  { key: 'keep', label: 'Keep' },
  { key: 'super_keep', label: 'Super keep' },
  { key: 'remove', label: 'Remove' },
  { key: 'skip', label: 'Skip' },
];
const SETTING_LABELS = {
  super_keep_multiplier: 'Super keep length',
  skip_hold_days: 'Skip hold',
  review_order: 'Review order',
  default_interval_hours: 'Starting interval',
  deck_size: 'Deck size',
  discovery_percent: 'For you discovery',
  not_now_percent: 'Not now strength',
  bring_back_recovery_days: 'Bring back recovery',
};
const SOURCE_LABELS = { bring_back: 'Bring back', picks: 'PlayLS picks', suggested: 'For you', search: 'Search' };

// ---------- formatting ----------
const dash = '—';
const pct = (v) => (v == null ? dash : `${Math.round(v * 100)}%`);
const ms = (v) => (v == null ? dash : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)}s`);
const secs = (v) => {
  if (v == null) return dash;
  const m = Math.floor(v / 60);
  const s = Math.round(v % 60);
  return m ? `${m}m ${s}s` : `${s}s`;
};
const num = (v) => (v == null ? dash : Number(v).toLocaleString());
const shortWeek = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

// ---------- building blocks ----------
const Section = ({ title, subtitle, children }) => (
  <Box component="section" mt={4}>
    <Typography variant="h6" component="h2">{title}</Typography>
    {subtitle && <Typography variant="body2" color="text.secondary" mb={1.5}>{subtitle}</Typography>}
    {children}
  </Box>
);

// A stat tile: the number is the chart. `delta` compares with the previous period (neutral ink).
const Stat = ({ label, value, previous, format = num, hint }) => {
  const showDelta = previous != null && value != null;
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ py: 2, '&:last-child': { pb: 2 } }}>
        <Typography variant="body2" color="text.secondary">{label}</Typography>
        <Typography sx={{ fontSize: '1.7rem', fontWeight: 600, lineHeight: 1.2, my: 0.5 }}>{format(value)}</Typography>
        <Typography variant="caption" color="text.secondary">
          {showDelta ? `Previous period: ${format(previous)}` : hint || ' '}
        </Typography>
      </CardContent>
    </Card>
  );
};

const StatRow = ({ children }) => (
  <Grid container spacing={2}>
    {React.Children.map(children, (child) => child && <Grid size={{ xs: 6, sm: 4, md: 2 }}>{child}</Grid>)}
  </Grid>
);

const DataTable = ({ columns, rows, dense = true }) => (
  <Box sx={{ overflowX: 'auto' }}>
    <Table size={dense ? 'small' : 'medium'}>
      <TableHead>
        <TableRow>{columns.map((c) => <TableCell key={c.key} align={c.align || 'left'}>{c.label}</TableCell>)}</TableRow>
      </TableHead>
      <TableBody>
        {rows.length === 0 && (
          <TableRow><TableCell colSpan={columns.length} sx={{ color: 'text.secondary' }}>No data yet</TableCell></TableRow>
        )}
        {rows.map((r, i) => (
          <TableRow key={i}>
            {columns.map((c) => (
              <TableCell key={c.key} align={c.align || 'left'} sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {c.format ? c.format(r[c.key], r) : r[c.key]}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </Box>
);

// A chart with a table view of the same numbers (values are never tooltip-only)
const ChartCard = ({ title, subtitle, table, children, empty }) => {
  const [view, setView] = useState('chart');
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={1} mb={1}>
          <Box minWidth={0}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{title}</Typography>
            {subtitle && <Typography variant="body2" color="text.secondary">{subtitle}</Typography>}
          </Box>
          {table && (
            <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}
              aria-label={`${title}: chart or table`}>
              <ToggleButton value="chart">Chart</ToggleButton>
              <ToggleButton value="table">Table</ToggleButton>
            </ToggleButtonGroup>
          )}
        </Box>
        {empty ? (
          <Typography color="text.secondary" py={4} textAlign="center">No data yet</Typography>
        ) : view === 'table' && table ? <DataTable {...table} /> : children}
      </CardContent>
    </Card>
  );
};

// Shared chart props: thin rounded bars, hairline horizontal grid, room for the axis band
const barProps = (height = 240) => ({
  height,
  borderRadius: 4,
  grid: { horizontal: true },
  margin: { left: 8, right: 8, top: 16, bottom: 8 },
});

// Weekday x hour heatmap (sequential blue), with a per-cell tooltip and a scale legend
const Heatmap = ({ grid, mode }) => {
  const ramp = HEAT[mode];
  const max = Math.max(1, ...grid.flat());
  const step = (n) => (n === 0 ? null : ramp[Math.min(ramp.length - 1, Math.floor((n / max) * (ramp.length - 1)))]);
  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: '36px repeat(24, minmax(14px, 1fr))', gap: '2px', minWidth: 420 }}>
        <Box />
        {Array.from({ length: 24 }, (_, h) => (
          <Typography key={h} variant="caption" color="text.secondary" textAlign="center" sx={{ fontSize: 10 }}>
            {h % 6 === 0 ? h : ''}
          </Typography>
        ))}
        {grid.map((row, d) => (
          <React.Fragment key={d}>
            <Typography variant="caption" color="text.secondary" sx={{ lineHeight: '18px' }}>{WEEKDAYS[d]}</Typography>
            {row.map((n, h) => (
              <Tooltip key={h} title={`${WEEKDAYS[d]} ${h}:00–${h + 1}:00 · ${n} decision${n === 1 ? '' : 's'}`}>
                <Box tabIndex={0} sx={{
                  height: 18, borderRadius: '3px', bgcolor: step(n) || 'action.hover',
                  outline: 'none', '&:focus-visible': { boxShadow: (t) => `0 0 0 2px ${t.palette.text.primary}` },
                }} />
              </Tooltip>
            ))}
          </React.Fragment>
        ))}
      </Box>
      <Box display="flex" alignItems="center" gap={0.5} mt={1.5}>
        <Typography variant="caption" color="text.secondary" mr={0.5}>Fewer</Typography>
        {ramp.map((c) => <Box key={c} sx={{ width: 16, height: 10, borderRadius: '2px', bgcolor: c }} />)}
        <Typography variant="caption" color="text.secondary" ml={0.5}>More decisions (local time)</Typography>
      </Box>
    </Box>
  );
};

const Counters = ({ title, values, labels }) => (
  <Card sx={{ height: '100%' }}>
    <CardContent>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>{title}</Typography>
      {Object.entries(labels).map(([key, label]) => (
        <Box key={key} display="flex" justifyContent="space-between" gap={2} py={0.25}>
          <Typography variant="body2" color="text.secondary">{label}</Typography>
          <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }}>{num(values?.[key] ?? 0)}</Typography>
        </Box>
      ))}
    </CardContent>
  </Card>
);

const DashboardSkeleton = () => (
  <Box>
    <Grid container spacing={2}>
      {Array.from({ length: 6 }, (_, i) => (
        <Grid key={i} size={{ xs: 6, sm: 4, md: 2 }}><Skeleton variant="rounded" height={104} /></Grid>
      ))}
    </Grid>
    <Grid container spacing={2} mt={2}>
      <Grid size={{ xs: 12, md: 6 }}><Skeleton variant="rounded" height={320} /></Grid>
      <Grid size={{ xs: 12, md: 6 }}><Skeleton variant="rounded" height={320} /></Grid>
    </Grid>
  </Box>
);

// ---------- the page ----------
const AdminStats = () => {
  const theme = useTheme();
  const mode = theme.palette.mode === 'dark' ? 'dark' : 'light';
  const colors = SERIES[mode];
  const [days, setDays] = useState(30);
  const [kind, setKind] = useState('all');
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    api.adminStats({ days, kind })
      .then((s) => { if (!cancelled) setStats(s); })
      .catch((e) => { if (!cancelled) setError(errorMessage(e, 'Failed to load stats.')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days, kind]);

  const view = useMemo(() => {
    if (!stats) return null;
    const d = stats.decisions;
    const weeks = d.mix_by_week.map((w) => shortWeek(w.week));
    return {
      weeks,
      mixSeries: ACTIONS.map((a, i) => ({
        id: a.key, label: a.label, data: d.mix_by_week.map((w) => w[a.key]), stack: 'mix', color: colors[i],
      })),
    };
  }, [stats, colors]);

  const now = stats?.kpis.current;
  const prev = stats?.kpis.previous;
  const lowData = stats && (now.sessions < 5 || now.decisions < 20);

  return (
    <Layout back="/">
      <Typography variant="h4" component="h1">Usage &amp; health</Typography>
      <Typography color="text.secondary" mb={2}>
        Usage from accounts that opted in, all combined; app health from every request (no accounts attached).
        Data older than {stats?.retention_days || 180} days is deleted.
      </Typography>

      {/* One filter row scopes everything below */}
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1, mb: 2 }}>
        {RANGES.map((r) => (
          <Chip key={r} label={`${r} days`} onClick={() => setDays(r)}
            color={days === r ? 'primary' : 'default'} variant={days === r ? 'filled' : 'outlined'} />
        ))}
        <Box sx={{ width: 8 }} />
        {KINDS.map((k) => (
          <Chip key={k.value} label={k.label} onClick={() => setKind(k.value)}
            color={kind === k.value ? 'primary' : 'default'} variant={kind === k.value ? 'filled' : 'outlined'} />
        ))}
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {!stats ? (loading && <DashboardSkeleton />) : (
        // Hold the previous numbers while a new range loads (no skeleton flash)
        <Box sx={{ opacity: loading ? 0.5 : 1, transition: 'opacity 150ms' }}>
          {lowData && (
            <Alert severity="info" sx={{ mb: 2 }}>
              Not much data in this range yet, so medians and percentages will move around as more sessions come in.
            </Alert>
          )}

          <StatRow>
            <Stat label="Review sessions" value={now.sessions} previous={prev.sessions} />
            <Stat label="Median session" value={now.session_median_s} previous={prev.session_median_s} format={secs} />
            <Stat label="Decisions" value={now.decisions} previous={prev.decisions} />
            <Stat label="Median decision time" value={now.decision_median_ms} previous={prev.decision_median_ms} format={ms} />
            <Stat label="Keep rate" value={now.keep_rate} previous={prev.keep_rate} format={pct} hint="Keeps + super keeps" />
            <Stat label="Remove rate" value={now.remove_rate} previous={prev.remove_rate} format={pct} />
          </StatRow>

          {/* ---------- reviewing ---------- */}
          <Section title="Reviewing" subtitle="Times exclude moments the app was in the background; long listens are capped at 10 minutes.">
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 7 }}>
                <ChartCard title="Decisions by week" subtitle="What people chose, stacked"
                  empty={view.weeks.length === 0}
                  table={{
                    columns: [{ key: 'week', label: 'Week of' }, ...ACTIONS.map((a) => ({ key: a.key, label: a.label, align: 'right' }))],
                    rows: stats.decisions.mix_by_week.map((w) => ({ ...w, week: shortWeek(w.week) })),
                  }}>
                  <BarChart {...barProps(260)} xAxis={[{ scaleType: 'band', data: view.weeks }]} series={view.mixSeries} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, md: 5 }}>
                <ChartCard title="Decision time" subtitle={`Median ${ms(stats.decisions.median_ms)} · p90 ${ms(stats.decisions.p90_ms)}`}
                  empty={stats.decisions.count === 0}
                  table={{ columns: [{ key: 'bucket', label: 'Time' }, { key: 'n', label: 'Decisions', align: 'right' }],
                    rows: stats.decisions.time_histogram }}>
                  <BarChart {...barProps()} hideLegend xAxis={[{ scaleType: 'band', data: stats.decisions.time_histogram.map((b) => b.bucket) }]}
                    series={[{ label: 'Decisions', data: stats.decisions.time_histogram.map((b) => b.n), color: colors[0] }]} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <ChartCard title="Session length"
                  subtitle={`Median ${secs(stats.sessions.median_s)} · p90 ${secs(stats.sessions.p90_s)} · ${num(stats.sessions.songs_median)} songs per session`}
                  empty={stats.sessions.count === 0}
                  table={{ columns: [{ key: 'bucket', label: 'Length' }, { key: 'n', label: 'Sessions', align: 'right' }],
                    rows: stats.sessions.length_histogram }}>
                  <BarChart {...barProps()} hideLegend xAxis={[{ scaleType: 'band', data: stats.sessions.length_histogram.map((b) => b.bucket) }]}
                    series={[{ label: 'Sessions', data: stats.sessions.length_histogram.map((b) => b.n), color: colors[0] }]} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <ChartCard title="Remove rate by song age"
                  subtitle="How long a song had been in the playlist (or since its last keep) when it was reviewed"
                  empty={stats.decisions.remove_rate_by_age.length === 0}
                  table={{ columns: [
                    { key: 'bucket', label: 'Song age' }, { key: 'n', label: 'Reviews', align: 'right' },
                    { key: 'remove_rate', label: 'Removed', align: 'right', format: pct },
                  ], rows: stats.decisions.remove_rate_by_age }}>
                  <BarChart {...barProps()} hideLegend
                    xAxis={[{ scaleType: 'band', data: stats.decisions.remove_rate_by_age.map((b) => b.bucket) }]}
                    yAxis={[{ valueFormatter: (v) => pct(v), max: 1 }]}
                    series={[{ label: 'Removed', data: stats.decisions.remove_rate_by_age.map((b) => b.remove_rate), color: colors[0],
                      valueFormatter: (v) => pct(v) }]} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, md: 7 }}>
                <ChartCard title="Fatigue: position in the batch"
                  subtitle="Do decisions get faster, or removals rarer, deeper into a session?">
                  <DataTable columns={[
                    { key: 'bucket', label: 'Song #' }, { key: 'n', label: 'Decisions', align: 'right' },
                    { key: 'remove_rate', label: 'Removed', align: 'right', format: pct },
                    { key: 'median_ms', label: 'Median time', align: 'right', format: ms },
                  ]} rows={stats.decisions.by_position} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, md: 5 }}>
                <Card sx={{ height: '100%' }}>
                  <CardContent>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>Habits</Typography>
                    {[
                      ['Sessions opened without deciding', num(stats.sessions.opened_without_deciding)],
                      ['Changed their mind (undo or re-answer)', pct(stats.decisions.changed_mind_share)],
                      ['Sessions per person per week (median)', num(stats.engagement.sessions_per_user_week_median)],
                      ['Days between sessions (median)', num(stats.engagement.days_between_sessions_median)],
                      ['Days overdue when reviewed (median)', num(stats.decisions.overdue_days_median)],
                      ...Object.entries(stats.decisions.input).map(([k, v]) => [`Decided by ${k}`, `${num(v)} (${pct(v / Math.max(1, stats.decisions.count))})`]),
                      ...Object.entries(stats.sessions.ended).map(([k, v]) => [`Sessions ended: ${k}`, num(v)]),
                    ].map(([label, value]) => (
                      <Box key={label} display="flex" justifyContent="space-between" gap={2} py={0.25}>
                        <Typography variant="body2" color="text.secondary">{label}</Typography>
                        <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{value}</Typography>
                      </Box>
                    ))}
                  </CardContent>
                </Card>
              </Grid>
              <Grid size={12}>
                <ChartCard title="When people review" subtitle="Decisions by weekday and hour, in each person's local time"
                  empty={stats.decisions.count === 0}
                  table={{
                    columns: [{ key: 'day', label: 'Day' }, ...Array.from({ length: 24 }, (_, h) => ({ key: `h${h}`, label: `${h}`, align: 'right' }))],
                    rows: stats.decisions.weekday_hour.map((row, i) => ({
                      day: WEEKDAYS[i], ...Object.fromEntries(row.map((n, h) => [`h${h}`, n])),
                    })),
                  }}>
                  <Heatmap grid={stats.decisions.weekday_hour} mode={mode} />
                </ChartCard>
              </Grid>
            </Grid>
          </Section>

          {/* ---------- you vs everyone ---------- */}
          <Section title="You vs everyone else" subtitle="Your own numbers next to the other opted-in accounts combined.">
            <Card><CardContent>
              <DataTable columns={[
                { key: 'metric', label: '' }, { key: 'you', label: 'You', align: 'right' },
                { key: 'others', label: 'Everyone else', align: 'right' },
              ]} rows={[
                ['Review sessions', 'sessions', num], ['Median session', 'session_median_s', secs],
                ['Decisions', 'decisions', num], ['Median decision time', 'decision_median_ms', ms],
                ['Keep rate', 'keep_rate', pct], ['Remove rate', 'remove_rate', pct],
              ].map(([metric, key, f]) => ({
                metric, you: f(stats.you_vs_everyone.you[key]), others: f(stats.you_vs_everyone.everyone_else[key]),
              }))} />
            </CardContent></Card>
          </Section>

          {/* ---------- restocking ---------- */}
          <Section title="Restocking" subtitle="Rates are out of cards answered (Skip records nothing).">
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 6 }}>
                <ChartCard title="Add rate by source" empty={stats.restock.by_source.length === 0}
                  table={{ columns: [
                    { key: 'source', label: 'Source', format: (v) => SOURCE_LABELS[v] || v },
                    { key: 'answered', label: 'Answered', align: 'right' }, { key: 'add', label: 'Added', align: 'right' },
                    { key: 'not_now', label: 'Not now', align: 'right' }, { key: 'block', label: 'Stopped', align: 'right' },
                    { key: 'undo', label: 'Undone', align: 'right' },
                    { key: 'add_rate', label: 'Add rate', align: 'right', format: pct },
                  ], rows: stats.restock.by_source }}>
                  <BarChart {...barProps()} hideLegend
                    xAxis={[{ scaleType: 'band', data: stats.restock.by_source.map((s) => SOURCE_LABELS[s.source] || s.source) }]}
                    yAxis={[{ valueFormatter: (v) => pct(v), max: 1 }]}
                    series={[{ label: 'Add rate', data: stats.restock.by_source.map((s) => s.add_rate), color: colors[0],
                      valueFormatter: (v) => pct(v) }]} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <ChartCard title="Restock by source" subtitle={`${num(stats.restock.sessions)} deck visits · ${num(stats.restock.adds)} songs added`}>
                  <DataTable columns={[
                    { key: 'source', label: 'Source', format: (v) => SOURCE_LABELS[v] || v },
                    { key: 'answered', label: 'Answered', align: 'right' },
                    { key: 'add', label: 'Added', align: 'right' }, { key: 'undo', label: 'Undone', align: 'right' },
                    { key: 'median_ms', label: 'Median time', align: 'right', format: ms },
                  ]} rows={stats.restock.by_source} />
                </ChartCard>
              </Grid>
            </Grid>
          </Section>

          {/* ---------- usage ---------- */}
          <Section title="Accounts & setup"
            subtitle="Consent counts cover every account; rotations and settings only opted-in ones.">
            <StatRow>
              <Stat label="Accounts" value={stats.usage.accounts} />
              <Stat label="Opted in" value={stats.usage.consent.yes} />
              <Stat label="Opted out" value={stats.usage.consent.no} />
              <Stat label="Not asked yet" value={stats.usage.consent.not_asked} />
              <Stat label="Manual rotations" value={stats.usage.rotations.manual} />
              <Stat label="Auto rotations" value={stats.usage.rotations.auto} />
            </StatRow>
            <Grid container spacing={2} mt={0}>
              <Grid size={{ xs: 12, md: 6 }}>
                <ChartCard title="Active people by week" empty={stats.usage.active_users_by_week.length === 0}
                  table={{ columns: [{ key: 'week', label: 'Week of' }, { key: 'users', label: 'People', align: 'right' }],
                    rows: stats.usage.active_users_by_week.map((w) => ({ ...w, week: shortWeek(w.week) })) }}>
                  <BarChart {...barProps(220)} hideLegend
                    xAxis={[{ scaleType: 'band', data: stats.usage.active_users_by_week.map((w) => shortWeek(w.week)) }]}
                    yAxis={[{ tickMinStep: 1 }]}
                    series={[{ label: 'People', data: stats.usage.active_users_by_week.map((w) => w.users), color: colors[0] }]} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, md: 6 }}>
                <ChartCard title="Settings people change"
                  subtitle={`Median rotation size ${num(stats.usage.rotations.songs_median)} songs`}>
                  <DataTable columns={[
                    { key: 'setting', label: 'Account setting' },
                    { key: 'share', label: 'Changed from default', align: 'right', format: pct },
                  ]} rows={Object.entries(stats.usage.settings_changed_share).map(([k, v]) => ({ setting: SETTING_LABELS[k] || k, share: v }))} />
                  <Typography variant="body2" color="text.secondary" mt={1.5}>
                    Rotation overrides: {Object.entries(stats.usage.rotation_overrides).filter(([, n]) => n > 0)
                      .map(([k, n]) => `${(SETTING_LABELS[k] || k.replaceAll('_', ' ')).toLowerCase()} ${n}`).join(' · ') || 'none'}
                  </Typography>
                </ChartCard>
              </Grid>
            </Grid>
          </Section>

          {/* ---------- health ---------- */}
          <Section title="App health"
            subtitle={`Latency from a ${pct(stats.health.sample_rate)} random sample of requests; errors, slow requests and sync events are always recorded.`}>
            <StatRow>
              <Stat label="Median request" value={stats.health.p50_ms} format={ms} />
              <Stat label="p95 request" value={stats.health.p95_ms} format={ms} />
              <Stat label="Server errors" value={stats.health.errors} />
              <Stat label="Rate limited (429)" value={stats.health.rate_limited_responses} />
              <Stat label="Slow (over 1.5s)" value={stats.health.slow} />
              <Stat label="Avg claim wait" value={stats.health.claim_wait_avg_ms} format={ms} />
            </StatRow>
            <Grid container spacing={2} mt={0}>
              <Grid size={12}>
                <ChartCard title="Problems by day" empty={stats.health.by_day.length === 0}
                  table={{ columns: [
                    { key: 'day', label: 'Day' }, { key: 'errors', label: 'Server errors', align: 'right' },
                    { key: 'rate_limited', label: 'Rate limited', align: 'right' }, { key: 'slow', label: 'Slow', align: 'right' },
                  ], rows: stats.health.by_day }}>
                  <LineChart height={240} grid={{ horizontal: true }} margin={{ left: 8, right: 16, top: 16, bottom: 8 }}
                    xAxis={[{ scaleType: 'point', data: stats.health.by_day.map((r) => shortWeek(r.day)) }]}
                    yAxis={[{ tickMinStep: 1 }]}
                    series={[
                      { label: 'Server errors', data: stats.health.by_day.map((r) => r.errors), color: colors[0], showMark: true },
                      { label: 'Rate limited', data: stats.health.by_day.map((r) => r.rate_limited), color: colors[1], showMark: true },
                      { label: 'Slow', data: stats.health.by_day.map((r) => r.slow), color: colors[2], showMark: true },
                    ]} />
                </ChartCard>
              </Grid>
              <Grid size={12}>
                <ChartCard title="Slowest routes" subtitle="By p95, from the sample. Request counts are estimated from the sample rate.">
                  <DataTable columns={[
                    { key: 'route', label: 'Route' }, { key: 'est_requests', label: '≈ Requests', align: 'right', format: num },
                    { key: 'p50_ms', label: 'p50', align: 'right', format: ms }, { key: 'p95_ms', label: 'p95', align: 'right', format: ms },
                    { key: 'spotify_ms_avg', label: 'Spotify avg', align: 'right', format: ms },
                    { key: 'db_ms_avg', label: 'DB avg', align: 'right', format: ms },
                    { key: 'db_connects_avg', label: 'DB connections', align: 'right' },
                  ]} rows={stats.health.by_route} />
                </ChartCard>
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 4 }}>
                <Counters title="Syncs" values={stats.health.counters.sync} labels={{
                  attempt: 'Attempts', fresh_skip: 'Reused a recent sync', unchanged: 'Unchanged (1 call)',
                  full_read: 'Full playlist reads', partial_read: 'Changed mid-read', failed: 'Failed',
                  flushed_songs: 'Removals sent',
                }} />
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 4 }}>
                <Counters title="Spotify" values={{ ...stats.health.counters.spotify, ...stats.health.spotify_errors }} labels={{
                  rate_limited: 'Rate limited', quota_exceeded: 'Quota exceeded', retry: 'Retries after 429',
                  token_refresh: 'Token refreshes (401)',
                  ...Object.fromEntries(Object.keys(stats.health.spotify_errors).map((k) => [k, `Errors ${k}`])),
                }} />
              </Grid>
              <Grid size={{ xs: 12, sm: 6, md: 4 }}>
                <Counters title="Auto rotations & cron" values={{
                  ...stats.health.counters.auto, ...Object.fromEntries(
                    Object.entries(stats.health.counters.cron).map(([k, v]) => [`cron_${k}`, v])),
                  ...Object.fromEntries(Object.entries(stats.health.counters.claim).map(([k, v]) => [`claim_${k}`, v])),
                }} labels={{
                  rotated_out: 'Songs rotated out', added: 'Songs added', short: 'Slots left unfilled', failed: 'Restock failures',
                  cron_rotations: 'Cron rotation runs', cron_failed: 'Cron failures',
                  claim_waited: 'Waited for a sync', claim_timeout: 'Gave up waiting',
                }} />
              </Grid>
              {stats.health.errors_by_route.length > 0 && (
                <Grid size={12}>
                  <ChartCard title="Server errors by route">
                    <DataTable columns={[{ key: 'route', label: 'Route' }, { key: 'n', label: 'Errors', align: 'right' }]}
                      rows={stats.health.errors_by_route} />
                  </ChartCard>
                </Grid>
              )}
            </Grid>
          </Section>
        </Box>
      )}
    </Layout>
  );
};

export default AdminStats;

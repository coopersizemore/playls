import React, { useRef, useState } from 'react';
import { Alert, Box, Button, LinearProgress, Typography } from '@mui/material';
import { UploadFile } from '@mui/icons-material';
import { api, errorMessage } from '../api';

// Spotify's "Extended streaming history" export: Streaming_History_Audio_*.json files, each an
// array of plays. The browser reads them and sends only song plays from the last year, in
// chunks (the server caps a request at 5,000 rows).
const CHUNK = 5000;
const YEAR_MS = 365 * 24 * 3600 * 1000;

const toRow = (entry) => {
  const uri = entry?.spotify_track_uri;
  if (typeof uri !== 'string' || !/^spotify:track:[A-Za-z0-9]+$/.test(uri) || !entry.ts) return null;
  const ts = new Date(entry.ts);
  if (Number.isNaN(ts.getTime()) || Date.now() - ts.getTime() > YEAR_MS) return null;
  const text = (v, max) => (typeof v === 'string' && v ? v.slice(0, max) : null);
  return {
    ts: ts.toISOString(),
    ms_played: Math.max(0, Math.min(Number(entry.ms_played) || 0, 24 * 3600 * 1000)),
    uri,
    track: text(entry.master_metadata_track_name, 300),
    artist: text(entry.master_metadata_album_artist_name, 500),
    album: text(entry.master_metadata_album_album_name, 300),
    reason_end: text(entry.reason_end, 40),
    skipped: typeof entry.skipped === 'boolean' ? entry.skipped : null,
  };
};

const ListeningImport = ({ onDone }) => {
  const input = useRef(null);
  const [progress, setProgress] = useState(null); // 0..100 while sending
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const importFiles = async (files) => {
    setError('');
    setResult(null);
    let rows = [];
    try {
      for (const file of files) {
        const entries = JSON.parse(await file.text());
        if (!Array.isArray(entries)) throw new Error('not a list');
        rows = rows.concat(entries.map(toRow).filter(Boolean));
      }
    } catch (e) {
      setError("Those files don't look like Spotify's Extended streaming history (Streaming_History_Audio_….json).");
      return;
    }
    if (rows.length === 0) {
      setError('No song plays from the last year were found in those files.');
      return;
    }
    const totals = { added: 0, duplicates: 0 };
    setProgress(0);
    try {
      for (let i = 0; i < rows.length; i += CHUNK) {
        const res = await api.importListening(rows.slice(i, i + CHUNK));
        totals.added += res.added;
        totals.duplicates += res.duplicates;
        setProgress(Math.round((100 * Math.min(rows.length, i + CHUNK)) / rows.length));
      }
      setResult(totals);
      onDone?.();
    } catch (e) {
      setError(errorMessage(e, 'The import stopped partway. Running it again picks up where it left off.'));
    } finally {
      setProgress(null);
    }
  };

  return (
    <Box mt={1}>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        For a fuller picture, request "Extended streaming history" in Spotify's account privacy settings (it
        takes a few days to arrive), then choose its Streaming_History_Audio files here. PlayLS keeps the
        last year, including which songs you skipped.
      </Typography>
      <input ref={input} type="file" accept=".json,application/json" multiple hidden
        onChange={(e) => { const files = [...e.target.files]; e.target.value = ''; if (files.length) importFiles(files); }} />
      <Button variant="outlined" startIcon={<UploadFile />} disabled={progress !== null}
        onClick={() => input.current?.click()}>
        Choose files
      </Button>
      {progress !== null && <LinearProgress variant="determinate" value={progress} sx={{ mt: 1.5 }} />}
      {result && (
        <Alert severity="success" sx={{ mt: 1.5 }}>
          Added {result.added.toLocaleString()} plays
          {result.duplicates > 0 && ` (${result.duplicates.toLocaleString()} were already saved)`}.
        </Alert>
      )}
      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
    </Box>
  );
};

export default ListeningImport;

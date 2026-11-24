// Usage analytics for the admin dashboard (docs/MONITORING_PLAN.md). Only when the user opted in
// (AuthContext sets it from /auth/me); the server checks consent again before storing anything.
// One session per Review / Restock page visit. Times exclude moments the tab was hidden.
import { API_BASE } from './api';

let enabled = false;
export const setTelemetryEnabled = (on) => { enabled = !!on; };

const uuid = () => {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  // Fallback (old browsers / insecure contexts): RFC 4122 v4 from getRandomValues or Math.random
  const bytes = window.crypto?.getRandomValues ? window.crypto.getRandomValues(new Uint8Array(16))
    : Uint8Array.from({ length: 16 }, () => Math.floor(Math.random() * 256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

// surface: 'review' | 'restock'. Returns an object to call as the page is used.
export const startSession = (surface, rotationId, source = null) => {
  const id = uuid();
  const now = () => performance.now();
  const started = now();
  let hiddenTotal = 0; // ms hidden since the session started
  let hiddenSince = document.visibilityState === 'hidden' ? now() : null;
  let cardShownAt = started;
  let cardHiddenAtShow = 0;
  let decisions = 0;
  let ended = false;

  const onVisibility = () => {
    if (document.visibilityState === 'hidden') {
      if (hiddenSince === null) hiddenSince = now();
    } else if (hiddenSince !== null) {
      hiddenTotal += now() - hiddenSince;
      hiddenSince = null;
    }
  };
  document.addEventListener('visibilitychange', onVisibility);

  const hiddenNow = () => hiddenTotal + (hiddenSince === null ? 0 : now() - hiddenSince);
  const elapsed = () => Math.max(0, Math.round(now() - started - hiddenNow()));

  return {
    id,
    // Call when a card appears
    cardShown() {
      cardShownAt = now();
      cardHiddenAtShow = hiddenNow();
    },
    // Telemetry for one decision, or undefined when analytics is off.
    // input: 'swipe' | 'button' | 'key'; revisit: answered again after going Back
    decision({ input, revisit = false, position } = {}) {
      if (!enabled) return undefined;
      decisions += 1;
      return {
        session_id: id,
        decision_ms: Math.max(0, Math.round(now() - cardShownAt - (hiddenNow() - cardHiddenAtShow))),
        session_elapsed_ms: elapsed(),
        input,
        revisit,
        position,
        tz_offset: new Date().getTimezoneOffset(),
      };
    },
    // ended: 'done' | 'stopped' | 'left' | 'exhausted'. Sent once; survives the page closing.
    end(how) {
      if (ended) return;
      ended = true;
      document.removeEventListener('visibilitychange', onVisibility);
      if (!enabled) return;
      try {
        fetch(`${API_BASE}/user/me/telemetry/session-end`, {
          method: 'POST',
          keepalive: true,
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({
            session_id: id, surface, rotation_id: rotationId ? Number(rotationId) : null, ended: how,
            decisions, session_elapsed_ms: elapsed(), tz_offset: new Date().getTimezoneOffset(),
            ...(source ? { source } : {}),
          }),
        }).catch(() => {});
      } catch (e) {
        // analytics is best-effort
      }
    },
  };
};

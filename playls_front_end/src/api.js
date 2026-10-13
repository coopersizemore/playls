import axios from 'axios';

// The API is served from the same origin under /api (Vercel services, `vercel dev`,
// or the CRA dev-server proxy in package.json).
export const API_BASE = '/api';

// Auth is an httpOnly session cookie the browser sends automatically. The backend
// rejects state-changing requests without this header (CSRF protection).
axios.defaults.headers.common['X-Requested-With'] = 'XMLHttpRequest';

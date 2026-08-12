import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// Bundled rather than loaded from a CDN, so math renders offline and under a strict CSP.
import App from './App.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

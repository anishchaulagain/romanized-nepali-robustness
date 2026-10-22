import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // In development, /api is forwarded to the FastAPI server so no VITE_API_URL is needed.
  server: { proxy: { '/api': 'http://localhost:8000' } },
});

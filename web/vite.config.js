// Vite is the build tool: it serves the app with hot-reload during
// development (`npm run dev`) and bundles it into static files for
// production (`npm run build` -> dist/).
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    // During development the React app runs on :5173 but the FastAPI backend
    // runs on :8000. This proxy forwards /api/* requests to the backend, so
    // the browser sees a single origin and session cookies just work.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})

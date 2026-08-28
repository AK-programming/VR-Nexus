import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Tailwind v4 is a Vite plugin, not a PostCSS plugin — there is no
// tailwind.config.js and no postcss.config.js. Theme tokens are declared with
// @theme inside src/index.css.
export default defineConfig({
  plugins: [react(), tailwindcss()],

  resolve: {
    // Must stay in step with "paths" in tsconfig.app.json.
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    port: 5173,
    // Proxying means the browser only ever talks to localhost:5173, so there is
    // no cross-origin request and no CORS config needed on the FastAPI side.
    // Backend binds to 127.0.0.1 explicitly, so don't use "localhost" here —
    // Node may resolve it to ::1 and the connection is refused.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})

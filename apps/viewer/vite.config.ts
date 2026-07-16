import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 4173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/artifacts': 'http://127.0.0.1:8000',
    },
  },
})

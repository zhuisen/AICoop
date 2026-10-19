import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        menubar: resolve(__dirname, 'menubar.html'),
        notch: resolve(__dirname, 'notch.html'),
        tpshover: resolve(__dirname, 'tps-hover.html'),
      },
    },
  },
})

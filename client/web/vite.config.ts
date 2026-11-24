import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发模式下 Vite 起 5173，把 /ws 代理到 Python 桥（8765）。
// 生产模式由桥自己托管 dist，同源，无需代理。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:8765', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    target: 'es2022',
    sourcemap: false,
  },
});

import { defineConfig, type UserConfig } from 'vite';
import react from '@vitejs/plugin-react';

const config = {
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    restoreMocks: true,
  },
  server: { host: '127.0.0.1', port: 5173 },
} as UserConfig & { test: { environment: string; setupFiles: string; restoreMocks: boolean } };

export default defineConfig(config);

import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import react from 'D:/DF11Studio/web_toolchain/node_modules/@vitejs/plugin-react/dist/index.js';
import tailwindcss from 'D:/DF11Studio/web_toolchain/node_modules/@tailwindcss/vite/dist/index.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const NM = 'D:/DF11Studio/web_toolchain/node_modules';

export default {
  root: __dirname,
  base: './',
  cacheDir: path.join(os.tmpdir(), 'df11-studio-vite-cache'),
  plugins: [react(), tailwindcss()],
  resolve: {
    preserveSymlinks: true,
    alias: {
      react: `${NM}/react`,
      'react-dom': `${NM}/react-dom`,
      'lucide-react': `${NM}/lucide-react`,
      '@testing-library/react': `${NM}/@testing-library/react`,
      '@testing-library/jest-dom': `${NM}/@testing-library/jest-dom`,
    },
  },
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    pool: 'forks',
    maxWorkers: 2,
    poolOptions: { forks: { execArgv: ['--preserve-symlinks'] } },
  },
};

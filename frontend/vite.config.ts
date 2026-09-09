import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
const proxy = { '/api': 'http://127.0.0.1:8765', '/healthz': 'http://127.0.0.1:8765' };
export default defineConfig({
  plugins: [react()], server: { proxy }, preview: { proxy },
  test: {
    environment: 'jsdom', setupFiles: ['./tests/setup.ts'], include: ['tests/**/*.test.{ts,tsx}'],
    reporters: ['default', ['junit', { outputFile: 'test-results/unit.xml' }]],
    coverage: { provider: 'v8', include: ['src/**/*.{ts,tsx}'],
      reporter: ['text', 'json-summary', 'lcov', 'html'],
      thresholds: { lines: 85, statements: 85, functions: 85, branches: 85 } }
  }
});

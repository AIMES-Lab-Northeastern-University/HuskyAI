import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Tests live in frontend/tests/, NOT under src/. backend/tests/
  // test_read_event_coverage.py scans src/**/*.{js,jsx} and treats any file
  // mentioning `artifact_state` / `section_updated` as a surface that must call
  // useSectionReadTracking. The GroupChat test has to push an artifact_state
  // payload, so keeping tests out of src/ is what stops them from either
  // tripping that guard or needing an EXEMPT entry to work around it.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './tests/setup.js',
    include: ['tests/**/*.test.{js,jsx}'],
    restoreMocks: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})

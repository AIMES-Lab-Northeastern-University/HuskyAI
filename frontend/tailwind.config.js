/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          0: '#0a0a0f',
          1: '#111118',
          2: '#1a1a24',
          3: '#22222e',
          4: '#2a2a38',
        },
        accent: {
          blue: '#C8102E',
          purple: '#FF6B8A',
          green: '#34d399',
          amber: '#fbbf24',
          red: '#f87171',
          cyan: '#22d3ee',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      }
    },
  },
  plugins: [],
}

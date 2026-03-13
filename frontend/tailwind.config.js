/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        red: {
          DEFAULT: '#C8102E',
          deep: '#9E0B24',
          light: '#FDE8EC',
          mid: '#F4B8C3',
        },
        cream: '#F7F3EE',
        warm: '#EDEAE4',
        ink: {
          DEFAULT: '#16120E',
          2: '#4A4440',
          3: '#9A948E',
        },
        white: '#FDFCFB',
        border: {
          DEFAULT: 'rgba(22,18,14,0.1)',
          solid: '#E7E0D8',
        },
        teal: {
          DEFAULT: '#0D9488',
          light: '#E6F7F6',
        },
        orange: {
          DEFAULT: '#F97316',
          light: '#FEF3E8',
        },
        green: {
          DEFAULT: '#16A34A',
          light: '#DCFCE7',
        },
        amber: {
          DEFAULT: '#D97706',
          light: '#FEF9EC',
        },
        purple: {
          DEFAULT: '#7C3AED',
          light: '#EDE9FE',
        },
      },
      fontFamily: {
        serif: ['"Instrument Serif"', 'serif'],
        sans: ['"DM Sans"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      borderWidth: {
        '1.5': '1.5px',
      },
      borderRadius: {
        DEFAULT: '8px',
        'sm': '6px',
        'md': '9px',
        'lg': '12px',
        'xl': '14px',
        '2xl': '16px',
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        forge: {
          bg: '#06060b',
          panel: '#0d0d15',
          border: '#1a1a2e',
          accent: '#6366f1',
          'accent-2': '#8b5cf6',
          success: '#22c55e',
          error: '#ef4444',
          warn: '#f59e0b',
          text: '#e2e8f0',
          muted: '#64748b',
          glow: 'rgba(99, 102, 241, 0.15)',
        },
      },
    },
  },
  plugins: [],
}

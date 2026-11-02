import daisyui from 'daisyui';

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx,vue}",
  ],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      colors: {
        darkBg: '#090d16',
        darkCard: '#111827',
        darkBorder: '#1f293d',
        accentGreen: '#10b981',
        accentRed: '#ef4444',
        accentBlue: '#38bdf8',
      }
    },
  },
  plugins: [daisyui],
  daisyui: {
    themes: [
      {
        dark: {
          "color-scheme": "dark",
          "primary": "#38bdf8",
          "primary-content": "#082f49",
          "secondary": "#818cf8",
          "secondary-content": "#1e1b4b",
          "accent": "#2dd4bf",
          "accent-content": "#134e4a",
          "neutral": "#1e293b",
          "neutral-content": "#f8fafc",
          "base-100": "#0b0f17",
          "base-200": "#111827",
          "base-300": "#1e293b",
          "base-content": "#f1f5f9",
          "info": "#38bdf8",
          "info-content": "#082f49",
          "success": "#10b981",
          "success-content": "#022c22",
          "warning": "#f59e0b",
          "warning-content": "#451a03",
          "error": "#ef4444",
          "error-content": "#450a0a",
          "--rounded-box": "0.75rem",
          "--rounded-btn": "0.5rem",
          "--rounded-badge": "9999px",
        },
        light: {
          "color-scheme": "light",
          "primary": "#0284c7",
          "primary-content": "#ffffff",
          "secondary": "#6366f1",
          "secondary-content": "#ffffff",
          "accent": "#0d9488",
          "accent-content": "#ffffff",
          "neutral": "#334155",
          "neutral-content": "#f8fafc",
          "base-100": "#ffffff",
          "base-200": "#f8fafc",
          "base-300": "#f1f5f9",
          "base-content": "#0f172a",
          "info": "#0284c7",
          "info-content": "#ffffff",
          "success": "#059669",
          "success-content": "#ffffff",
          "warning": "#d97706",
          "warning-content": "#ffffff",
          "error": "#dc2626",
          "error-content": "#ffffff",
          "--rounded-box": "0.75rem",
          "--rounded-btn": "0.5rem",
          "--rounded-badge": "9999px",
        }
      },
      "dark",
      "light"
    ],
    darkTheme: "dark",
    base: true,
    styled: true,
    utils: true,
  },
};

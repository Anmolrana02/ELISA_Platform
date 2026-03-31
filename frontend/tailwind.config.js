// Paste contents from the generated tailwind.config.js here
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        soil:  '#2D1F14',
        earth: '#4A3728',
        clay:  '#8B5E3C',
        wheat: '#D4A53F',
        green: { DEFAULT: '#1D9E75', dark: '#156B50', light: '#D1F0E5' },
        alert: { DEFAULT: '#C45C3A', light: '#FCE8E2' },
        sky:   { DEFAULT: '#4A9CC4', light: '#DFF0F8' },
        paper: '#F5F0E8',
        mist:  '#EBE5D9',
        stone: '#C8BFB0',
      },
      fontFamily: {
        display: ['Outfit', 'sans-serif'],
        body:    ['DM Sans', 'sans-serif'],
        mono:    ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        sm: '6px', md: '10px', lg: '16px', xl: '24px',
      },
    },
  },
  plugins: [],
}
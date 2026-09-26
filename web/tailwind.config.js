/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#fff1f5',
          100: '#ffe4ec',
          200: '#fecdd9',
          300: '#fda4be',
          400: '#fb7199',
          500: '#ff7597',
          600: '#f43f6e',
          700: '#e11d53',
          800: '#be1243',
          900: '#9f123c',
        },
        sky: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
        brand: {
          sakura: '#ff7597',
          pink: '#ff8fab',
          sky: '#38bdf8',
          azure: '#60a5fa',
        }
      },
      backgroundImage: {
        'gradient-primary': 'linear-gradient(135deg, #ff8fab 0%, #38bdf8 100%)',
        'gradient-sakura': 'linear-gradient(135deg, #ff7597 0%, #f472b6 100%)',
        'gradient-sky': 'linear-gradient(135deg, #38bdf8 0%, #60a5fa 100%)',
        'gradient-success': 'linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%)',
        'gradient-warning': 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
        'gradient-danger': 'linear-gradient(135deg, #fb7185 0%, #e11d48 100%)',
        'gradient-info': 'linear-gradient(135deg, #38bdf8 0%, #2563eb 100%)',
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'shimmer': 'linear-gradient(90deg, transparent, rgba(255,255,255,0.6), transparent)',
      },
      boxShadow: {
        'glow': '0 0 20px rgba(255, 117, 151, 0.4)',
        'glow-lg': '0 0 30px rgba(255, 117, 151, 0.6)',
        'glow-sky': '0 0 20px rgba(56, 189, 248, 0.4)',
        'inner-glow': 'inset 0 0 20px rgba(255, 117, 151, 0.2)',
        'glass': '0 8px 32px 0 rgba(255, 117, 151, 0.12)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-in-left': 'slideInLeft 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'scale-in': 'scaleIn 0.3s ease-out',
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'shimmer': 'shimmer 2s infinite',
        'float': 'float 4s ease-in-out infinite',
        'glow': 'glow 2.5s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInLeft: {
          '0%': { opacity: '0', transform: 'translateX(-20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-1000px 0' },
          '100%': { backgroundPosition: '1000px 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        glow: {
          '0%, 100%': { boxShadow: '0 0 6px rgba(255, 117, 151, 0.4)' },
          '50%': { boxShadow: '0 0 22px rgba(56, 189, 248, 0.55)' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
}
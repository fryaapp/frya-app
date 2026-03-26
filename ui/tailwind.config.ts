import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['Outfit', 'sans-serif'],
        body: ['"Plus Jakarta Sans"', 'sans-serif'],
      },
      colors: {
        primary: 'var(--frya-primary)',
        'on-primary': 'var(--frya-on-primary)',
        'primary-container': 'var(--frya-primary-container)',
        'on-primary-container': 'var(--frya-on-primary-container)',
        'secondary-container': 'var(--frya-secondary-container)',
        'on-secondary-container': 'var(--frya-on-secondary-container)',
        'tertiary-container': 'var(--frya-tertiary-container)',
        'on-tertiary-container': 'var(--frya-on-tertiary-container)',
        surface: 'var(--frya-surface)',
        'on-surface': 'var(--frya-on-surface)',
        'on-surface-variant': 'var(--frya-on-surface-variant)',
        'surface-container': 'var(--frya-surface-container)',
        'surface-container-low': 'var(--frya-surface-container-low)',
        'surface-container-lowest': 'var(--frya-surface-container-lowest)',
        'surface-container-high': 'var(--frya-surface-container-high)',
        outline: 'var(--frya-outline)',
        'outline-variant': 'var(--frya-outline-variant)',
        error: 'var(--frya-error)',
        'error-container': 'var(--frya-error-container)',
        success: 'var(--frya-success)',
        'success-container': 'var(--frya-success-container)',
        warning: 'var(--frya-warning)',
        'warning-container': 'var(--frya-warning-container)',
        info: 'var(--frya-info)',
        'info-container': 'var(--frya-info-container)',
        'page-bg': 'var(--frya-page-bg)',
      },
      borderRadius: {
        'm3-sm': '8px',
        'm3': '12px',
        'm3-lg': '16px',
        'm3-xl': '28px',
      },
    },
  },
  plugins: [],
} satisfies Config

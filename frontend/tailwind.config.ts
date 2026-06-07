import type { Config } from 'tailwindcss';

export default {
	darkMode: 'class',
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {
			colors: {
				rb: {
					50: '#fffef0',
					100: '#fffcd6',
					200: '#fff899',
					300: '#fff04d',
					400: '#ffe333',
					500: '#ffd700',
					600: '#d4a800',
					700: '#a87a00',
					800: '#8a6000',
					900: '#6a4a00',
					950: '#3d2900'
				},
				accent: {
					DEFAULT: '#ffd700',
					foreground: '#1a1a1a'
				},
				surface: {
					DEFAULT: '#f5f5f5',
					muted: '#f8f9fa',
					alt: '#f1f3f5',
					border: '#e9ecef',
					hover: '#f1f3f5'
				},
				dark: {
					bg: '#0a0a0a',
					surface: '#141414',
					elevated: '#1c1c1e',
					border: '#2c2c2e',
					hover: '#2c2c2e',
					muted: '#a1a1aa',
					text: '#e4e4e7'
				}
			},
			fontFamily: {
				sans: [
					'Inter',
					'-apple-system',
					'BlinkMacSystemFont',
					'Segoe UI',
					'Roboto',
					'sans-serif'
				],
				mono: ['JetBrains Mono', 'Fira Code', 'monospace']
			},
			animation: {
				'fade-in': 'fadeIn 0.3s ease-out',
				'slide-up': 'slideUp 0.3s ease-out',
				'pulse-dot': 'pulseDot 1.4s infinite ease-in-out',
				'typing-cursor': 'blink 1s step-end infinite'
			},
			keyframes: {
				fadeIn: {
					'0%': { opacity: '0', transform: 'translateY(8px)' },
					'100%': { opacity: '1', transform: 'translateY(0)' }
				},
				slideUp: {
					'0%': { opacity: '0', transform: 'translateY(16px)' },
					'100%': { opacity: '1', transform: 'translateY(0)' }
				},
				pulseDot: {
					'0%, 80%, 100%': { transform: 'scale(0.6)', opacity: '0.4' },
					'40%': { transform: 'scale(1)', opacity: '1' }
				},
				blink: {
					'0%, 100%': { opacity: '1' },
					'50%': { opacity: '0' }
				}
			}
		}
	},
	plugins: [require('@tailwindcss/typography')]
} satisfies Config;

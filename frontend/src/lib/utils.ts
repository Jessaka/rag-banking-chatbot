import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export function generateId(): string {
	return crypto.randomUUID();
}

export function formatTime(ms: number): string {
	if (ms < 1000) return `${Math.round(ms)} ms`;
	return `${(ms / 1000).toFixed(1)} s`;
}

export function truncate(str: string, length: number): string {
	if (str.length <= length) return str;
	return str.slice(0, length) + '…';
}

export function formatSourceTitle(fileName: string): string {
	return fileName
		.replace(/\.pdf$/i, '')
		.replace(/^pricing_/i, '')
		.replace(/[-_]/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function cn(...inputs: ClassValue[]) {
        return twMerge(clsx(inputs));
}
export function generateId(): string {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
                return crypto.randomUUID();
        }
        return Math.random().toString(36).substring(2) + Date.now().toString(36);
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
export function getSourceHumanTitle(source: { human_title?: string | null; file_name: string }): string {
        if (source.human_title && source.human_title.length > 3) {
                return source.human_title;
        }
        return formatSourceTitle(source.file_name);
}
export function getSourceDisplayUrl(source: { display_url?: string | null }): string | null {
        return source.display_url ?? null;
}

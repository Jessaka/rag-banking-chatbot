import type { ChatRequest, ChatResponse } from './types';

const API_BASE: string =
	(typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || 'http://localhost:8000';

console.debug('[API] resolved API_BASE:', API_BASE);

export async function sendChatMessage(
	question: string,
	sessionId?: string | null,
	abortSignal?: AbortSignal
): Promise<ChatResponse> {
	const body: ChatRequest = { question, session_id: sessionId || null };
	const url = `${API_BASE}/chat`;

	console.debug('[API] fetch', { url, body });

	const response = await fetch(url, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
		signal: abortSignal
	});

	console.debug('[API] response status:', response.status);

	if (!response.ok) {
		const errorText = await response.text().catch(() => 'Unknown error');
		throw new Error(`API error ${response.status}: ${errorText}`);
	}

	return response.json() as Promise<ChatResponse>;
}

/**
 * Streaming chat via SSE (Server-Sent Events).
 *
 * Yields parsed SSE events: 'start', 'token', 'done', 'error'.
 * Supports cancellation via AbortSignal.
 */
export async function* streamChatMessage(
	question: string,
	sessionId?: string | null,
	abortSignal?: AbortSignal
): AsyncGenerator<{ event: string; data: Record<string, unknown> }, void, void> {
	const body: ChatRequest = { question, session_id: sessionId || null };
	const url = `${API_BASE}/chat/stream`;

	console.debug('[API] SSE stream', { url, body });

	const response = await fetch(url, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
		signal: abortSignal,
	});

	if (!response.ok) {
		const errorText = await response.text().catch(() => 'Unknown error');
		throw new Error(`SSE error ${response.status}: ${errorText}`);
	}

	const reader = response.body?.getReader();
	if (!reader) throw new Error('SSE: no response body');

	const decoder = new TextDecoder();
	let buffer = '';

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, { stream: true });

			// Parse SSE events from buffer
			const lines = buffer.split('\n');
			buffer = lines.pop() ?? '';

			let currentEvent = '';
			let currentData = '';

			for (const line of lines) {
				if (line.startsWith('event: ')) {
					currentEvent = line.slice(7).trim();
				} else if (line.startsWith('data: ')) {
					currentData = line.slice(6).trim();
				} else if (line === '') {
					// Empty line = end of event
					if (currentEvent && currentData) {
						try {
							const parsed = JSON.parse(currentData) as Record<string, unknown>;
							yield { event: currentEvent, data: parsed };
						} catch (parseErr) {
							console.warn('[SSE] parse error', currentEvent, currentData, parseErr);
						}
					}
					currentEvent = '';
					currentData = '';
				}
			}
		}
	} finally {
		reader.releaseLock();
	}
}

export async function checkHealth(): Promise<boolean> {
	const url = `${API_BASE}/health`;
	console.debug('[API] health check', { url });
	try {
		const response = await fetch(url, {
			signal: AbortSignal.timeout(3000)
		});
		console.debug('[API] health response:', response.status);
		return response.ok;
	} catch (err) {
		console.debug('[API] health failed', { error: err instanceof Error ? err.message : err });
		return false;
	}
}

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

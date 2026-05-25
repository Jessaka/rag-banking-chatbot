export type ChatTelemetryPayload = Record<string, unknown>;

export function emitChatEvent(name: string, detail: ChatTelemetryPayload = {}) {
	if (typeof window === 'undefined') return;
	window.dispatchEvent(
		new CustomEvent('rb-chat-telemetry', {
			detail: {
				name,
				timestamp: Date.now(),
				...detail
			}
		})
	);
}

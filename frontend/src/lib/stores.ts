import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';
import type { Message, Conversation } from './types';

// --- Theme ---
type Theme = 'light' | 'dark';
const storedTheme = browser ? (localStorage.getItem('rb-theme') as Theme | null) : null;
export const theme = writable<Theme>(storedTheme || 'dark');
theme.subscribe((value) => {
	if (browser) {
		localStorage.setItem('rb-theme', value);
		document.documentElement.classList.toggle('dark', value === 'dark');
	}
});

// --- Sidebar ---
export const sidebarOpen = writable(false);

// --- Debug panel ---
export const debugPanelOpen = writable(false);

// --- Loading ---
export const isLoading = writable(false);
export const currentRequestId = writable<string | null>(null);

// --- Error ---
export const error = writable<string | null>(null);

// --- Sessions / Conversations ---
function loadConversations(): Conversation[] {
	if (!browser) return [];
	try {
		const stored = localStorage.getItem('rb-conversations');
		return stored ? JSON.parse(stored) : [];
	} catch {
		return [];
	}
}

function saveConversations(conversations: Conversation[]) {
	if (browser) {
		localStorage.setItem('rb-conversations', JSON.stringify(conversations));
	}
}

export const conversations = writable<Conversation[]>(loadConversations());
export const currentSessionId = writable<string | null>(null);

// Derive current conversation
export const currentConversation = derived(
	[conversations, currentSessionId],
	([$conversations, $currentSessionId]) => {
		if (!$currentSessionId) {
			console.debug('[store] currentConversation: null (no sessionId)');
			return null;
		}
		const found = $conversations.find((c) => c.id === $currentSessionId) || null;
		console.debug('[store] currentConversation derived', {
			sessionId: $currentSessionId,
			found: !!found,
			conversationTitle: found?.title?.slice(0, 40),
			messageCount: found?.messages?.length
		});
		return found;
	}
);

// Derive current messages
export const messages = derived(currentConversation, ($conv) => {
	const msgs = $conv?.messages || [];
	if (msgs.length > 0) {
		const last = msgs[msgs.length - 1];
		console.debug('[store] messages derived', {
			length: msgs.length,
			lastRole: last.role,
			lastContentPreview: last.content?.slice(0, 50)
		});
	} else {
		console.debug('[store] messages derived: empty');
	}
	return msgs;
});

export function createConversation(title: string = 'Nový rozhovor', id?: string | null): Conversation {
	return {
		id: id || crypto.randomUUID(),
		title,
		messages: [],
		createdAt: Date.now(),
		updatedAt: Date.now()
	};
}

export function addMessageToConversation(
	sessionId: string,
	message: Message
) {
	conversations.update((convos) => {
		const updated = convos.map((c) => {
			if (c.id !== sessionId) return c;
			return {
				...c,
				messages: [...c.messages, message],
				updatedAt: Date.now(),
				title:
					c.messages.length === 0 && message.role === 'user'
						? message.content.slice(0, 60).replace(/\n/g, ' ')
						: c.title
			};
		});
		saveConversations(updated);
		return updated;
	});
}

export function deleteConversation(sessionId: string) {
	conversations.update((convos) => {
		const updated = convos.filter((c) => c.id !== sessionId);
		saveConversations(updated);
		return updated;
	});
	currentSessionId.update((id) => (id === sessionId ? null : id));
}

export function clearAllConversations() {
	conversations.set([]);
	if (browser) localStorage.removeItem('rb-conversations');
	currentSessionId.set(null);
}

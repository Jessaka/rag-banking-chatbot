<script lang="ts">
	import { onMount } from 'svelte';
	import {
		isLoading,
		messages,
		conversations,
		currentSessionId,
		currentConversation,
		createConversation,
		addMessageToConversation,
		error,
		currentRequestId
	} from '$lib/stores';
	import { sendChatMessage } from '$lib/api';
	import { generateId } from '$lib/utils';
	import type { Message } from '$lib/types';
	import ChatMessage from './ChatMessage.svelte';
	import ChatInput from './ChatInput.svelte';
	import DebugPanel from './DebugPanel.svelte';
	import TypingIndicator from './TypingIndicator.svelte';
	import { emitChatEvent } from '$lib/monitoring';
	import { Button } from '$ui';
	import { Sparkles } from '@lucide/svelte';

	let messagesContainer: HTMLDivElement | null = $state(null);
	let abortController: AbortController | null = $state(null);

	// Auto-scroll when messages change
	$effect(() => {
		$messages; // subscribe
		if (messagesContainer) {
			requestAnimationFrame(() => {
				if (!messagesContainer) return;
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			});
		}
	});

	async function handleSubmit(text: string) {
		// Create or get session
		let sessionId = $currentSessionId;
		console.debug('[Chat] handleSubmit', { text, sessionId });

		if (!sessionId) {
			sessionId = generateId();
			currentSessionId.set(sessionId);
			conversations.update((c) => [createConversation(text, sessionId), ...c]);
			console.debug('[Chat] created conversation', {
				sessionId,
				newConversationId: sessionId,
				conversationsCount: $conversations.length,
				messagesBefore: $messages.length
			});
		}

		// Add user message
		const userMsg: Message = {
			id: generateId(),
			role: 'user',
			content: text,
			timestamp: Date.now()
		};
		addMessageToConversation(sessionId, userMsg);
		console.debug('[Chat] added user message', {
			msgId: userMsg.id,
			currentConv: $currentConversation?.id,
			messagesLength: $messages.length
		});

		// Add placeholder assistant message
		const assistantId = generateId();
		const assistantMsg: Message = {
			id: assistantId,
			role: 'assistant',
			content: '',
			timestamp: Date.now()
		};
		addMessageToConversation(sessionId, assistantMsg);
		console.debug('[Chat] added placeholder assistant', {
			assistantId,
			currentConv: $currentConversation?.id,
			messagesLength: $messages.length
		});

		// Call API
		isLoading.set(true);
		error.set(null);
		abortController = new AbortController();

		try {
			emitChatEvent('chat_request_started', { session_id: sessionId });
			console.debug('[Chat] fetching /chat', {
				payload: { question: text, session_id: sessionId }
			});
			const response = await sendChatMessage(text, sessionId, abortController.signal);
			console.debug('[Chat] raw API response', {
				answer_length: response.answer?.length,
				sources_count: response.sources?.length,
				strategy: response.answer_strategy,
				processing_time_ms: response.processing_time_ms
			});

			currentRequestId.set(response.request_id);
			emitChatEvent('chat_response_received', {
				session_id: response.session_id,
				request_id: response.request_id,
				answer_strategy: response.answer_strategy,
				confidence_bucket: response.confidence_bucket,
				processing_time_ms: response.processing_time_ms,
				sources_count: response.sources?.length || 0,
				unsupported: Boolean(response.unsupported_reason),
				clarification_required: Boolean(response.clarification_required)
			});

			// Update the assistant message with real response
			conversations.update((convos) => {
				const updated = convos.map((c) => {
					if (c.id !== sessionId) return c;
					return {
						...c,
						messages: c.messages.map((m) =>
							m.id === assistantId
								? {
										...m,
										content: response.answer,
										sources: response.sources || [],
										retrieval_debug: response.retrieval_debug || null,
										answer_strategy: response.answer_strategy,
										confidence_bucket: response.confidence_bucket || null,
										confidence_reason: response.confidence_reason || null,
										clarification_required: response.clarification_required || false,
										unsupported_reason: response.unsupported_reason || null,
										processing_time_ms: response.processing_time_ms,
										request_id: response.request_id,
										error: false
									}
								: m
						)
					};
				});
				const target = updated.find((c) => c.id === sessionId);
				console.debug('[Chat] assistant message updated', {
					assistantId,
					foundConversation: !!target,
					messageCount: target?.messages?.length,
					lastMessageContent: target?.messages?.[target.messages.length - 1]?.content?.slice(0, 80)
				});
				return updated;
			});
		} catch (err: unknown) {
			if (err instanceof Error && err.name === 'AbortError') {
				console.debug('[Chat] request aborted');
				return;
			}

			const errorMsg = err instanceof Error ? err.message : 'Neočekávaná chyba';
			console.error('[Chat] request failed', { error: errorMsg, err });
			emitChatEvent('chat_request_failed', { session_id: sessionId, error: errorMsg });
			error.set(errorMsg);

			// Mark assistant message as error
			conversations.update((convos) =>
				convos.map((c) => {
					if (c.id !== sessionId) return c;
					return {
						...c,
						messages: c.messages.map((m) =>
							m.id === assistantId
								? { ...m, content: `❌ ${errorMsg}`, error: true }
								: m
						)
					};
				})
			);
		} finally {
			isLoading.set(false);
			abortController = null;
		}
	}

	function retry() {
		const msgs = $messages;
		if (msgs.length < 2) return;
		const lastUserMsg = [...msgs].reverse().find((m) => m.role === 'user');
		if (lastUserMsg) {
			// Remove last assistant + user messages and retry
			// Actually simpler: just re-submit the last user question
			handleSubmit(lastUserMsg.content);
		}
	}

	function submitSuggestion(text: string) {
		handleSubmit(text);
	}

	// Handle AbortController cleanup
	onMount(() => {
		return () => {
			abortController?.abort();
		};
	});
</script>

<div class="mx-auto flex h-full max-w-3xl flex-col">
	<!-- Messages -->
	<div
		bind:this={messagesContainer}
		class="flex-1 overflow-y-auto px-4 py-6"
	>
		{#if $messages.length === 0}
			<!-- Empty state -->
			<div class="flex h-full flex-col items-center justify-center text-center">
				<div class="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-rb-100 dark:bg-rb-900/20">
					<Sparkles class="h-8 w-8 text-rb-500" />
				</div>
				<h1 class="text-xl font-semibold text-gray-900 dark:text-dark-text">
					AI Bankovní Asistent
				</h1>
				<p class="mt-2 max-w-md text-sm text-gray-500 dark:text-gray-400">
					Zeptejte se na cokoli ohledně produktů, poplatků a služeb Raiffeisenbank.
				</p>
				<div class="mt-8 grid w-full max-w-md grid-cols-1 gap-2 sm:grid-cols-2">
					{#each [
						'Jaký je poplatek za vedení běžného účtu?',
						'Kolik stojí vedení eKonta?',
						'Co mám dělat při podezření na phishing?',
						'Jaké typy platebních karet nabízíte?'
					] as suggestion}
						<button
							onclick={() => handleSubmit(suggestion)}
							disabled={$isLoading}
							class="rounded-xl border bg-white p-3 text-left text-xs text-gray-600 shadow-sm transition-colors hover:bg-surface-hover disabled:opacity-50 dark:bg-dark-surface dark:border-dark-border dark:text-gray-300 dark:hover:bg-dark-hover"
						>
							{suggestion}
						</button>
					{/each}
				</div>
			</div>
		{:else}
			<div class="space-y-8">
				{#each $messages as msg, i}
					<ChatMessage
						message={msg}
						isLatest={i === $messages.length - 1}
						onretry={msg.error ? retry : undefined}
						onask={submitSuggestion}
					/>
				{/each}

				<!-- Loading indicator -->
				{#if $isLoading}
					<TypingIndicator label="AI připravuje odpověď…" />
				{/if}
			</div>

			<!-- Debug panel (only on latest assistant message) -->
			{#if $messages.length > 0}
				{@const lastMsg = $messages[$messages.length - 1]}
				{#if lastMsg.role === 'assistant' && !lastMsg.error && lastMsg.answer_strategy}
					<div class="mt-4 space-y-2">
						<DebugPanel
							strategy={lastMsg.answer_strategy}
							confidence={lastMsg.confidence_bucket}
							latency={lastMsg.processing_time_ms}
							debug={lastMsg.retrieval_debug}
							sources={(lastMsg.sources || []).map(s => ({ file_name: s.file_name, page: s.page, rerank_score: s.rerank_score }))}
						/>
					</div>
				{/if}
			{/if}
		{/if}
	</div>

	<!-- Input -->
	<div class="border-t bg-white/80 backdrop-blur-xl px-4 py-4 dark:bg-dark-bg/80 dark:border-dark-border">
		<ChatInput disabled={$isLoading} onsubmit={handleSubmit} />
	</div>
</div>

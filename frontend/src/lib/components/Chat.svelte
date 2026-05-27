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
	import { sendChatMessage, streamChatMessage } from '$lib/api';
	import { generateId } from '$lib/utils';
	import type { Message, SourceDocument, ConfidenceBucket } from '$lib/types';
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

		// Try streaming first; fall back to blocking API
		let usedStreaming = false;

		try {
			emitChatEvent('chat_request_started', { session_id: sessionId });
			console.debug('[Chat] fetching /chat/stream', {
				payload: { question: text, session_id: sessionId }
			});

			const stream = streamChatMessage(text, sessionId, abortController.signal);
			let fullAnswer = '';
			let startData: Record<string, unknown> | null = null;
			let doneData: Record<string, unknown> | null = null;
			let errorData: Record<string, unknown> | null = null;

			for await (const event of stream) {
				if (event.event === 'start') {
					startData = event.data;
					// Update assistant message with metadata as it arrives
					conversations.update((convos) =>
						convos.map((c) => {
							if (c.id !== sessionId) return c;
							return {
								...c,
								messages: c.messages.map((m) =>
									m.id === assistantId
										? {
												...m,
												sources: (event.data.sources as SourceDocument[]) || [],
												answer_strategy: (event.data.answer_strategy as string) || null,
												confidence_bucket: (event.data.answer_confidence as ConfidenceBucket) || null,
												clarification_required: (event.data.clarification_required as boolean) || false,
												unsupported_reason: (event.data.unsupported_reason as string) || null,
												error: false
											}
										: m
								)
							};
						})
					);
				} else if (event.event === 'token') {
					const token = event.data.text as string;
					fullAnswer += token;
					usedStreaming = true;
					// Progressively update assistant message content
					conversations.update((convos) =>
						convos.map((c) => {
							if (c.id !== sessionId) return c;
							return {
								...c,
								messages: c.messages.map((m) =>
									m.id === assistantId ? { ...m, content: fullAnswer } : m
								)
							};
						})
					);
				} else if (event.event === 'done') {
					doneData = event.data;
				} else if (event.event === 'error') {
					errorData = event.data;
					console.error('[Chat] SSE error', event.data);
				}
			}

			if (errorData) {
				throw new Error((errorData.detail as string) || (errorData.error as string) || 'SSE error');
			}

			const streamRequestId = (startData?.request_id as string) || null;

			// Finalize assistant message with timing info
			conversations.update((convos) =>
				convos.map((c) => {
					if (c.id !== sessionId) return c;
					return {
						...c,
						messages: c.messages.map((m) =>
							m.id === assistantId
								? {
										...m,
										content: fullAnswer,
										processing_time_ms: (doneData?.processing_time_ms as number) || undefined,
										retrieval_latency_ms: (doneData?.retrieval_latency_ms as number) || null,
										llm_latency_ms: (doneData?.llm_latency_ms as number) || null,
										formatting_latency_ms: (doneData?.formatting_latency_ms as number) || null,
										request_id: streamRequestId,
									}
								: m
						)
					};
				})
			);

			const sId = (startData?.session_id as string) || sessionId;
			if (streamRequestId) currentRequestId.set(streamRequestId);
			emitChatEvent('chat_response_received', {
				session_id: sId,
				request_id: streamRequestId,
				answer_strategy: (startData?.answer_strategy as string) || null,
				confidence_bucket: (startData?.answer_confidence as string) || null,
				processing_time_ms: (doneData?.processing_time_ms as number) || 0,
				sources_count: ((startData?.sources) as unknown[])?.length || 0,
				unsupported: Boolean(startData?.unsupported_reason),
				clarification_required: Boolean(startData?.clarification_required)
			});
		} catch (err: unknown) {
			if (err instanceof Error && err.name === 'AbortError') {
				console.debug('[Chat] request aborted');
				return;
			}

			// If streaming failed (e.g., endpoint not available), fall back to blocking API
			if (!usedStreaming) {
				console.warn('[Chat] streaming failed, falling back to /chat', err);
				try {
					const response = await sendChatMessage(text, sessionId, abortController?.signal);
					// Update the assistant message with the full response
					conversations.update((convos) =>
						convos.map((c) => {
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
						})
					);
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
				} catch (fallbackErr: unknown) {
					if (fallbackErr instanceof Error && fallbackErr.name === 'AbortError') {
						console.debug('[Chat] request aborted during fallback');
						return;
					}
					// Final error handling
					const fallbackMsg = fallbackErr instanceof Error ? fallbackErr.message : 'Neočekávaná chyba';
					console.error('[Chat] fallback also failed', { error: fallbackMsg, fallbackErr });
					emitChatEvent('chat_request_failed', { session_id: sessionId, error: fallbackMsg });
					error.set(fallbackMsg);
					conversations.update((convos) =>
						convos.map((c) => {
							if (c.id !== sessionId) return c;
							return {
								...c,
								messages: c.messages.map((m) =>
									m.id === assistantId
										? { ...m, content: `❌ ${fallbackMsg}`, error: true }
										: m
								)
							};
						})
					);
				}
			} else {
				// Streaming was partially in progress — keep what we have
				console.warn('[Chat] streaming ended with error after partial content', err);
				// Partial content is already in the message, just mark it
				conversations.update((convos) =>
					convos.map((c) => {
						if (c.id !== sessionId) return c;
						return {
							...c,
							messages: c.messages.map((m) =>
								m.id === assistantId ? { ...m, error: false } : m
							)
						};
					})
				);
			}
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
							retrieval_latency={lastMsg.retrieval_latency_ms}
							llm_latency={lastMsg.llm_latency_ms}
							formatting_latency={lastMsg.formatting_latency_ms}
							debug={lastMsg.retrieval_debug}
							sources={(lastMsg.sources || []).map(s => ({ file_name: s.file_name, page: s.page, rerank_score: s.rerank_score, human_title: s.human_title }))}
							confidenceSemanticLabel={lastMsg.confidence_semantic_label}
							confidenceOriginLabel={lastMsg.confidence_origin_label}
							degraded={lastMsg.degraded_answer}
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

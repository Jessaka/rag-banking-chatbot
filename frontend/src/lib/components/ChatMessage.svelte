<script lang="ts">
	import type { Message } from '$lib/types';
	import { cn, formatTime } from '$lib/utils';
	import Markdown from './Markdown.svelte';
	import SourcesCard from './SourcesCard.svelte';
	import ConfidenceBadge from './ConfidenceBadge.svelte';
	import ClarificationChips from './ClarificationChips.svelte';
	import GuidedFlowCard from './GuidedFlowCard.svelte';
	import UnsupportedCard from './UnsupportedCard.svelte';
	import EscalationCTA from './EscalationCTA.svelte';
	import MessageActions from './MessageActions.svelte';
	import { clarificationOptions, isGuidedFlow, isUnsupported, shouldShowEscalation } from '$lib/chat-ux';
	import { emitChatEvent } from '$lib/monitoring';
	import { isLoading } from '$lib/stores';
	import { User, Bot, RotateCcw, AlertCircle } from '@lucide/svelte';
	import { Button } from '$ui';

	let {
		message,
		isLatest = false,
		onretry,
		onask
	}: {
		message: Message;
		isLatest?: boolean;
		onretry?: () => void;
		onask?: (text: string) => void;
	} = $props();

	let displayContent = $state('');
	let isTyping = $state(false);
	let typingComplete = $state(false);

	// Display logic for the latest assistant message.
	//
	// During SSE streaming ($isLoading = true): show tokens directly as they arrive.
	// The interval-based animation must NOT run here — each new token triggers the
	// $effect, which would reset displayContent = '' and restart the interval, causing
	// the displayed text to flicker and reset instead of accumulating progressively.
	//
	// After streaming completes ($isLoading = false): run a one-shot typing animation
	// on the finalised content (only for the latest message shown to the user).
	$effect(() => {
		if (!isLatest || message.role !== 'assistant' || message.error) {
			// Historical messages and user messages: show content directly.
			displayContent = message.content;
			typingComplete = true;
			isTyping = false;
			return;
		}

		if ($isLoading) {
			// Actively streaming: show tokens directly without animation.
			// Each token already arrives as a progressive update from Chat.svelte.
			displayContent = message.content;
			isTyping = true;
			typingComplete = false;
			return;
		}

		// Streaming complete: run one-shot animation on the final content.
		isTyping = true;
		typingComplete = false;
		displayContent = '';

		const fullText = message.content;
		if (!fullText) {
			typingComplete = true;
			isTyping = false;
			return;
		}

		let index = 0;
		const charsPerTick = 3;
		const interval = setInterval(() => {
			index += charsPerTick;
			if (index >= fullText.length) {
				displayContent = fullText;
				typingComplete = true;
				isTyping = false;
				clearInterval(interval);
			} else {
				displayContent = fullText.slice(0, index);
			}
		}, 20);

		return () => clearInterval(interval);
	});

	$effect(() => {
		if (message.role === 'assistant' && message.content && message.confidence_bucket) {
			emitChatEvent('chat_confidence_shown', {
				message_id: message.id,
				confidence_bucket: message.confidence_bucket,
				answer_strategy: message.answer_strategy
			});
		}
	});
</script>

<div class="animate-fade-in group">
	<div class="flex gap-3 sm:gap-4">
		<!-- Avatar -->
		<div
			class={cn(
				'flex h-8 w-8 shrink-0 items-center justify-center rounded-xl',
				message.role === 'assistant' && 'bg-rb-100 dark:bg-rb-900/20',
				message.role === 'user' && 'bg-gray-100 dark:bg-dark-elevated'
			)}
		>
			{#if message.role === 'assistant'}
				<Bot class="h-4 w-4 text-rb-600 dark:text-rb-400" />
			{:else}
				<User class="h-4 w-4 text-gray-500 dark:text-gray-400" />
			{/if}
		</div>

		<!-- Content -->
		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-2">
				<span class="text-sm font-medium text-gray-900 dark:text-dark-text">
					{message.role === 'assistant' ? 'AI Asistent' : 'Vy'}
				</span>
				<span class="text-[11px] text-gray-400 dark:text-gray-500">
					{new Date(message.timestamp).toLocaleTimeString('cs', { hour: '2-digit', minute: '2-digit' })}
				</span>
				{#if message.processing_time_ms}
					<span class="text-[11px] text-gray-400 dark:text-gray-500">
						· {formatTime(message.processing_time_ms)}
					</span>
				{/if}
			</div>

			<div class="mt-1.5">
				{#if message.error}
					<div class="flex items-start gap-2 rounded-xl bg-red-50 p-3 dark:bg-red-900/10">
						<AlertCircle class="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
						<div>
							<p class="text-sm text-red-700 dark:text-red-400">
								{message.content || 'Došlo k chybě při zpracování dotazu.'}
							</p>
							{#if onretry}
								<Button variant="ghost" size="sm" onclick={onretry} class="mt-2 text-red-600 dark:text-red-400">
									<RotateCcw class="mr-1.5 h-3.5 w-3.5" />
									Zkusit znovu
								</Button>
							{/if}
						</div>
					</div>
				{:else if message.role === 'assistant'}
					<div class="mb-2">
						<ConfidenceBadge bucket={message.confidence_bucket} reason={message.confidence_reason} />
					</div>

					{#if isGuidedFlow(message)}
						<GuidedFlowCard content={displayContent} onask={onask} />
					{:else if isUnsupported(message)}
						<UnsupportedCard content={displayContent} reason={message.unsupported_reason} onask={onask} />
					{:else}
						<div class="prose-custom">
							<Markdown content={displayContent} />
						</div>
					{/if}

					{#if isTyping && !typingComplete}
						<span class="inline-flex gap-0.5 ml-0.5">
							<span class="typing-dot h-1.5 w-1.5 animate-pulse-dot rounded-full bg-gray-400 dark:bg-gray-500"></span>
							<span class="typing-dot h-1.5 w-1.5 animate-pulse-dot rounded-full bg-gray-400 dark:bg-gray-500" style="animation-delay: 0.2s"></span>
							<span class="typing-dot h-1.5 w-1.5 animate-pulse-dot rounded-full bg-gray-400 dark:bg-gray-500" style="animation-delay: 0.4s"></span>
						</span>
					{/if}

					{#if typingComplete && message.clarification_required}
						<div class="mt-3">
							<ClarificationChips options={clarificationOptions(message)} onselect={onask} />
						</div>
					{/if}

					{#if typingComplete && shouldShowEscalation(message) && !isGuidedFlow(message) && !isUnsupported(message)}
						<div class="mt-3">
							<EscalationCTA variant={message.confidence_bucket === 'low' ? 'low-confidence' : 'default'} onask={onask} />
						</div>
					{/if}

					{#if typingComplete && message.sources && message.sources.length > 0}
						<div class="mt-3">
							<SourcesCard sources={message.sources} strategy={message.answer_strategy} />
						</div>
					{/if}

					{#if typingComplete}
						<MessageActions content={message.content} canRetry={message.error || message.confidence_bucket === 'low'} onretry={onretry} />
					{/if}
				{:else}
					<div class="prose-custom">
						<p class="text-sm text-gray-700 dark:text-gray-300">{message.content}</p>
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.typing-dot {
		animation: pulseDot 1.4s infinite ease-in-out both;
	}
</style>

<script lang="ts">
	import { Check, Copy, RotateCcw } from '@lucide/svelte';
	import { Button } from '$ui';
	import { emitChatEvent } from '$lib/monitoring';

	let {
		content = '',
		canRetry = false,
		onretry
	}: {
		content?: string;
		canRetry?: boolean;
		onretry?: () => void;
	} = $props();

	let copied = $state(false);

	async function copyAnswer() {
		await navigator.clipboard?.writeText(content);
		copied = true;
		emitChatEvent('chat_copy_clicked', { chars: content.length });
		setTimeout(() => (copied = false), 1400);
	}

	function retry() {
		emitChatEvent('chat_retry_clicked');
		onretry?.();
	}
</script>

<div class="mt-2 flex flex-wrap gap-1 opacity-100 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100">
	<Button variant="ghost" size="sm" onclick={copyAnswer} disabled={!content} aria-label="Kopírovat odpověď">
		{#if copied}<Check class="mr-1 h-3.5 w-3.5" />Zkopírováno{:else}<Copy class="mr-1 h-3.5 w-3.5" />Kopírovat{/if}
	</Button>
	{#if canRetry}
		<Button variant="ghost" size="sm" onclick={retry} aria-label="Zkusit znovu">
			<RotateCcw class="mr-1 h-3.5 w-3.5" />Zkusit znovu
		</Button>
	{/if}
</div>

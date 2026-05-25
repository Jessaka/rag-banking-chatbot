<script lang="ts">
	import { HelpCircle } from '@lucide/svelte';
	import { Button } from '$ui';
	import { emitChatEvent } from '$lib/monitoring';

	let {
		options = [],
		onselect
	}: {
		options?: string[];
		onselect?: (value: string) => void;
	} = $props();

	function choose(value: string) {
		emitChatEvent('chat_clarification_chip_clicked', { value });
		onselect?.(value);
	}
</script>

<div class="rounded-2xl border border-amber-200 bg-amber-50/70 p-3 dark:border-amber-900/40 dark:bg-amber-900/10">
	<div class="mb-2 flex items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-300">
		<HelpCircle class="h-4 w-4" />
		Potřebuji upřesnění
	</div>
	{#if options.length > 0}
		<div class="flex flex-wrap gap-2">
			{#each options as option}
				<Button variant="outline" size="sm" onclick={() => choose(option)}>{option}</Button>
			{/each}
		</div>
	{:else}
		<p class="text-xs text-amber-700 dark:text-amber-300">Napište prosím krátké upřesnění do chatu.</p>
	{/if}
</div>

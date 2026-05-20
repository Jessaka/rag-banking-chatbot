<script lang="ts">
	import { debugPanelOpen } from '$lib/stores';
	import { formatTime } from '$lib/utils';
	import { ChevronDown, ChevronUp, Bug, Clock, Target } from '@lucide/svelte';
	import { Badge, Button } from '$ui';

	let {
		strategy = null,
		confidence = null,
		latency = null as number | null,
		debug = null as unknown | null,
		sources = [] as Array<{ file_name: string; page: number | null; rerank_score: number | null }>
	}: {
		strategy?: string | null;
		confidence?: string | null;
		latency?: number | null;
		debug?: unknown | null;
		sources?: Array<{ file_name: string; page: number | null; rerank_score: number | null }>;
	} = $props();

	let isOpen = $state(false);

	$effect(() => {
		isOpen = $debugPanelOpen;
	});

	function toggle() {
		isOpen = !isOpen;
		debugPanelOpen.set(isOpen);
	}
</script>

<div class="rounded-2xl border bg-white dark:bg-dark-surface dark:border-dark-border overflow-hidden transition-all">
	<button
		onclick={toggle}
		class="flex w-full items-center justify-between px-4 py-3 text-sm transition-colors hover:bg-surface-hover dark:hover:bg-dark-hover"
	>
		<span class="flex items-center gap-2 font-medium text-gray-700 dark:text-gray-300">
			<Bug class="h-4 w-4 text-gray-400" />
			Debug
		</span>
		{#if isOpen}
			<ChevronUp class="h-4 w-4 text-gray-400" />
		{:else}
			<ChevronDown class="h-4 w-4 text-gray-400" />
		{/if}
	</button>

	{#if isOpen && strategy}
		<div class="border-t px-4 py-3 space-y-3 dark:border-dark-border">
			<!-- Strategy & Confidence -->
			<div class="flex flex-wrap items-center gap-2">
				{#if strategy}
					<Badge variant={strategy === 'pricing_row_direct' ? 'success' : 'default'}>
						{strategy}
					</Badge>
				{/if}
				{#if confidence}
					<Badge variant={confidence === 'high' ? 'success' : 'warning'}>
						{confidence}
					</Badge>
				{/if}
				{#if latency != null}
					<span class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
						<Clock class="h-3 w-3" />
						{formatTime(latency)}
					</span>
				{/if}
			</div>

			<!-- Top sources -->
			{#if sources.length > 0}
				<div>
					<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Top zdroje</p>
					<div class="space-y-1">
						{#each sources.slice(0, 3) as src}
							<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
								<span class="truncate text-gray-700 dark:text-gray-300">{src.file_name}</span>
								<span class="ml-2 shrink-0 text-gray-400">
									{src.rerank_score?.toFixed(3) ?? '—'}
								</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Raw debug JSON -->
			{#if debug}
				<details class="group">
					<summary class="cursor-pointer text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
						Raw retrieval debug
					</summary>
					<pre class="mt-1.5 max-h-48 overflow-auto rounded-lg bg-gray-50 p-2 text-[10px] leading-relaxed text-gray-600 dark:bg-dark-elevated dark:text-gray-400"><code>{JSON.stringify(debug, null, 2)}</code></pre>
				</details>
			{/if}
		</div>
	{/if}
</div>

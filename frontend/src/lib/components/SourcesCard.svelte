<script lang="ts">
	import type { SourceDocument } from '$lib/types';
	import { formatSourceTitle } from '$lib/utils';
	import { ChevronDown, ChevronUp, FileText, ExternalLink } from '@lucide/svelte';
	import { Badge, Button } from '$ui';

	let {
		sources = [],
		open = false
	}: {
		sources?: SourceDocument[];
		open?: boolean;
	} = $props();

	let isOpen = $state(open);
	// Sync with prop changes (sources panel can be opened externally)
	$effect(() => {
		isOpen = open;
	});
</script>

{#if sources.length > 0}
	<div class="rounded-2xl border bg-white dark:bg-dark-surface dark:border-dark-border overflow-hidden transition-all">
		<button
			onclick={() => isOpen = !isOpen}
			class="flex w-full items-center justify-between px-4 py-3 text-sm transition-colors hover:bg-surface-hover dark:hover:bg-dark-hover"
		>
			<span class="flex items-center gap-2 font-medium text-gray-700 dark:text-gray-300">
				<FileText class="h-4 w-4 text-rb-500" />
				Zdrojové dokumenty
				<Badge variant="secondary">{sources.length}</Badge>
			</span>
			{#if isOpen}
				<ChevronUp class="h-4 w-4 text-gray-400" />
			{:else}
				<ChevronDown class="h-4 w-4 text-gray-400" />
			{/if}
		</button>

		{#if isOpen}
			<div class="border-t divide-y dark:border-dark-border dark:divide-dark-border">
				{#each sources as source}
					<div class="px-4 py-3 transition-colors hover:bg-surface-hover dark:hover:bg-dark-hover">
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0 flex-1">
								<p class="text-sm font-medium text-gray-900 dark:text-dark-text truncate">
									{formatSourceTitle(source.file_name)}
								</p>
								<div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
									{#if source.page != null}
										<span>Str. {source.page}</span>
									{/if}
									{#if source.rerank_score != null}
										<span>Skóre: {source.rerank_score.toFixed(3)}</span>
									{/if}
								</div>
							</div>
						</div>
						{#if source.preview}
							<p class="mt-1.5 text-xs text-gray-400 dark:text-gray-500 line-clamp-2 leading-relaxed">
								{source.preview}
							</p>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<script lang="ts">
	import type { SourceDocument } from '$lib/types';
	import { sourceRationale } from '$lib/chat-ux';
	import { emitChatEvent } from '$lib/monitoring';
	import { getSourceHumanTitle, getSourceDisplayUrl } from '$lib/utils';
	import { ChevronDown, ChevronUp, FileText } from '@lucide/svelte';
	import { Badge } from '$ui';

	let {
		sources = [],
		open = false,
		strategy = null
	}: {
		sources?: SourceDocument[];
		open?: boolean;
		strategy?: string | null;
	} = $props();

	let isOpen = $state(false);
	$effect(() => {
		isOpen = open;
	});

	function toggle() {
		isOpen = !isOpen;
		emitChatEvent('chat_source_expanded', { open: isOpen, sources_count: sources.length });
	}

	// Badge color mapping
	function badgeVariant(badge: string | null | undefined): 'default' | 'secondary' | 'outline' | 'success' | 'warning' {
		switch (badge) {
			case 'Aktuální': return 'success';
			case 'Ceník': return 'default';
			case 'FAQ': return 'default';
			case 'Podmínky': return 'warning';
			case 'Archivní': return 'secondary';
			default: return 'outline';
		}
	}
</script>

{#if sources.length > 0}
	<div class="rounded-2xl border bg-white dark:bg-dark-surface dark:border-dark-border overflow-hidden transition-all">
		<button
			onclick={toggle}
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
								<!-- Human-readable title -->
								<p class="text-sm font-medium text-gray-900 dark:text-dark-text truncate">
									{getSourceHumanTitle(source)}
								</p>
								<!-- Badge + page + year row -->
								<div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
									{#if source.current_or_archived}
										<Badge variant={badgeVariant(source.current_or_archived)}>
											{source.current_or_archived}
										</Badge>
									{:else}
										<Badge variant="outline">Dokument</Badge>
									{/if}
									{#if source.source_year}
										<span>{source.source_year}</span>
									{/if}
									{#if source.page != null}
										<span>Str. {source.page}</span>
									{/if}
								</div>
								<!-- Display URL -->
								{#if source.display_url}
									<p class="mt-0.5 text-xs text-gray-400 dark:text-gray-500 truncate font-mono">
										{source.display_url}
									</p>
								{/if}
								<!-- Rationale -->
								<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{sourceRationale(source, strategy)}</p>
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

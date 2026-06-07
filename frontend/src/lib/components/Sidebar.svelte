<script lang="ts">
	import { sidebarOpen, sidebarCollapsed, conversations, currentSessionId, deleteConversation } from '$lib/stores';
	import { fade } from 'svelte/transition';
	import { X, Trash2 } from '@lucide/svelte';
	import { Button } from '$ui';

	function selectConversation(id: string) {
		currentSessionId.set(id);
		sidebarOpen.set(false);
	}

	function formatDate(ts: number): string {
		const d = new Date(ts);
		const now = new Date();
		const diff = now.getTime() - d.getTime();
		if (diff < 86400000) return d.toLocaleTimeString('cs', { hour: '2-digit', minute: '2-digit' });
		if (diff < 604800000) return d.toLocaleDateString('cs', { weekday: 'short' });
		return d.toLocaleDateString('cs', { day: 'numeric', month: 'short' });
	}
</script>

<!-- Mobile overlay -->
{#if $sidebarOpen}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_interactive_supports_focus -->
	<div
		class="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm lg:hidden"
		onclick={() => sidebarOpen.set(false)}
		onkeydown={(e) => e.key === 'Escape' && sidebarOpen.set(false)}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
		transition:fade={{ duration: 200 }}
	></div>
{/if}

<!-- Sidebar -->
<aside
	class="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-gray-200
	       bg-[#eeeeee]/95 backdrop-blur-sm
	       dark:bg-dark-surface/95 dark:border-dark-border
	       transition-all duration-300
	       lg:relative lg:translate-x-0 {$sidebarCollapsed ? 'lg:w-0 lg:overflow-hidden' : 'lg:w-72'}"
	class:translate-x-0={$sidebarOpen}
	class:-translate-x-full={!$sidebarOpen}
>
	<!-- Header — minimální, jen X pro mobile -->
	<div class="flex h-12 shrink-0 items-center justify-between px-4 dark:border-dark-border">
		<span class="text-[10px] font-medium uppercase tracking-widest text-gray-400 dark:text-gray-600">
			Rozhovory
		</span>
		<Button variant="ghost" size="icon" onclick={() => sidebarOpen.set(false)} class="lg:hidden">
			<X class="h-4 w-4" />
		</Button>
	</div>

	<!-- Conversation list -->
	<div class="flex-1 overflow-y-auto px-2 pb-2">
		{#if $conversations.length === 0}
			<div class="flex flex-col items-center justify-center py-16 text-center">
				<p class="text-xs text-gray-400 dark:text-gray-500">Zatím žádné rozhovory</p>
			</div>
		{:else}
			<div class="space-y-px">
				{#each $conversations as conv (conv.id)}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						onclick={() => selectConversation(conv.id)}
						onkeydown={(e) => e.key === 'Enter' && selectConversation(conv.id)}
						role="button"
						tabindex="0"
						class="group relative w-full cursor-pointer rounded-lg px-3 py-2 text-left transition-colors
						       {$currentSessionId === conv.id
								? 'bg-white dark:bg-dark-elevated'
								: 'hover:bg-black/5 dark:hover:bg-white/5'}"
					>
						<div class="flex items-baseline justify-between gap-2">
							<p class="truncate text-sm text-gray-800 dark:text-dark-text leading-snug">
								{conv.title}
							</p>
							<span class="shrink-0 text-[10px] text-gray-400 dark:text-gray-600">
								{formatDate(conv.updatedAt)}
							</span>
						</div>
						<button
							onclick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }}
							class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-gray-300 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100 dark:text-gray-600 dark:hover:text-red-400"
						>
							<Trash2 class="h-3 w-3" />
						</button>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Footer -->
	<div class="shrink-0 border-t border-gray-200/60 p-3 dark:border-dark-border">
		<p class="text-center text-[10px] text-gray-300 dark:text-gray-700">
			Raiffeisenbank AI Asistent
		</p>
	</div>
</aside>

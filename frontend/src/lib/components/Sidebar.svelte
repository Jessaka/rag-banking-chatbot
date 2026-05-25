<script lang="ts">
	import { sidebarOpen, conversations, currentSessionId, deleteConversation } from '$lib/stores';
	import { fade } from 'svelte/transition';
	import { X, Plus, Trash2, MessageSquare, RotateCcw } from '@lucide/svelte';
	import { Button } from '$ui';

	function selectConversation(id: string) {
		currentSessionId.set(id);
		sidebarOpen.set(false);
	}

	function newChat() {
		currentSessionId.set(null);
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

	<!-- Overlay for mobile -->
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
	class="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r bg-white dark:bg-dark-surface dark:border-dark-border transition-transform duration-300 lg:relative lg:translate-x-0"
	class:translate-x-0={$sidebarOpen}
	class:-translate-x-full={!$sidebarOpen}
>
	<!-- Header -->
	<div class="flex h-14 items-center justify-between border-b px-4 dark:border-dark-border">
		<span class="text-sm font-semibold text-gray-900 dark:text-dark-text">Historie</span>
		<div class="flex items-center gap-1">
			<Button variant="ghost" size="icon" onclick={newChat}>
				<Plus class="h-4 w-4" />
			</Button>
			<Button variant="ghost" size="icon" onclick={() => sidebarOpen.set(false)} class="lg:hidden">
				<X class="h-4 w-4" />
			</Button>
		</div>
	</div>

	<!-- Conversation list -->
	<div class="flex-1 overflow-y-auto p-2">
		{#if $conversations.length === 0}
			<div class="flex flex-col items-center justify-center py-16 text-center">
				<MessageSquare class="mb-3 h-8 w-8 text-gray-300 dark:text-gray-600" />
				<p class="text-sm text-gray-400 dark:text-gray-500">Zatím žádné rozhovory</p>
			</div>
		{:else}
			{#each $conversations as conv (conv.id)}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					onclick={() => selectConversation(conv.id)}
					onkeydown={(e) => e.key === 'Enter' && selectConversation(conv.id)}
					role="button"
					tabindex="0"
					class="group relative w-full cursor-pointer rounded-xl px-3 py-2.5 text-left text-sm transition-colors hover:bg-surface-hover dark:hover:bg-dark-hover"
					class:bg-surface-alt!={$currentSessionId === conv.id}
					class:dark:bg-dark-elevated!={$currentSessionId === conv.id}
				>
					<div class="flex items-start gap-2.5">
						<MessageSquare class="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400 dark:text-gray-500" />
						<div class="min-w-0 flex-1">
							<p class="truncate text-gray-900 dark:text-dark-text">{conv.title}</p>
							<p class="mt-0.5 text-xs text-gray-400 dark:text-gray-500">{formatDate(conv.updatedAt)} · {conv.messages.length} zpráv</p>
						</div>
					</div>
					<button
						onclick={(e) => { e.stopPropagation(); deleteConversation(conv.id); }}
						class="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-gray-400 opacity-0 transition-opacity hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 dark:hover:bg-red-900/20 dark:hover:text-red-400"
					>
						<Trash2 class="h-3.5 w-3.5" />
					</button>
				</div>
			{/each}
		{/if}
	</div>

	<!-- Footer -->
	<div class="border-t p-3 dark:border-dark-border">
		<p class="text-center text-xs text-gray-400 dark:text-gray-600">
			Raiffeisenbank AI Asistent
		</p>
	</div>
</aside>

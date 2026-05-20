<script lang="ts">
	import { sidebarOpen, clearAllConversations, currentSessionId } from '$lib/stores';
	import ThemeToggle from './ThemeToggle.svelte';
	import { Menu, Plus, Trash2 } from '@lucide/svelte';
	import { Button } from '$ui';

	function newChat() {
		currentSessionId.set(null);
	}
</script>

<header class="sticky top-0 z-30 border-b bg-white/80 backdrop-blur-xl dark:bg-dark-bg/80 dark:border-dark-border">
	<div class="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
		<div class="flex items-center gap-3">
			<button
				onclick={() => sidebarOpen.set(true)}
				class="flex h-9 w-9 items-center justify-center rounded-xl text-gray-500 transition-colors hover:bg-surface-hover dark:text-gray-400 dark:hover:bg-dark-hover lg:hidden"
				aria-label="Otevřít postranní panel"
			>
				<Menu class="h-4 w-4" />
			</button>

			<!-- RB Logo placeholder -->
			<a href="/" class="flex items-center gap-2.5">
				<div class="flex h-8 w-8 items-center justify-center rounded-lg bg-rb-400">
					<span class="text-xs font-bold text-black">RB</span>
				</div>
				<span class="hidden text-sm font-semibold text-gray-900 dark:text-dark-text sm:block">
					AI Asistent
				</span>
			</a>
		</div>

		<div class="flex items-center gap-1.5">
			<Button variant="ghost" size="sm" onclick={newChat}>
				<Plus class="mr-1.5 h-3.5 w-3.5" />
				Nový dotaz
			</Button>

			{#if $currentSessionId}
				<Button variant="ghost" size="icon" onclick={clearAllConversations}>
					<Trash2 class="h-4 w-4" />
				</Button>
			{/if}

			<ThemeToggle />
		</div>
	</div>
</header>

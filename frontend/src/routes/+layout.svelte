<script lang="ts">
	import '../app.css';
	import Header from '$lib/components/Header.svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import { theme, sidebarCollapsed } from '$lib/stores';
	import { ChevronLeft, ChevronRight } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	let { children }: { children?: Snippet } = $props();

	$effect(() => {
		const saved = localStorage.getItem('rb-theme');
		if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
			document.documentElement.classList.add('dark');
			theme.set('dark');
		} else {
			document.documentElement.classList.remove('dark');
			theme.set('light');
		}
	});
</script>

<div class="flex h-screen overflow-hidden bg-surface dark:bg-dark-bg">
	<Sidebar />

	<!-- Desktop sidebar toggle tab — sits right at the sidebar border -->
	<div class="relative z-40 hidden lg:flex items-center -ml-px">
		<button
			class="flex h-10 w-4 items-center justify-center
			       border-y border-r border-gray-200 dark:border-dark-border
			       bg-white dark:bg-dark-surface rounded-r-md shadow-sm
			       text-gray-400 hover:text-gray-600 dark:text-gray-600 dark:hover:text-gray-400
			       hover:bg-gray-50 dark:hover:bg-dark-elevated transition-colors"
			onclick={() => sidebarCollapsed.update((v) => !v)}
			aria-label="Přepnout postranní panel"
		>
			{#if $sidebarCollapsed}
				<ChevronRight class="h-3 w-3" />
			{:else}
				<ChevronLeft class="h-3 w-3" />
			{/if}
		</button>
	</div>

	<div class="flex flex-1 flex-col min-w-0">
		<Header />
		<main class="flex-1 overflow-hidden">
			{@render children?.()}
		</main>
	</div>
</div>

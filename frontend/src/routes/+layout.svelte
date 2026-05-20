<script lang="ts">
	import '../app.css';
	import Header from '$lib/components/Header.svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import { theme } from '$lib/stores';
	import type { Snippet } from 'svelte';

	let { children }: { children?: Snippet } = $props();

	// Apply initial theme on mount
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

	<div class="flex flex-1 flex-col min-w-0">
		<Header />
		<main class="flex-1 overflow-hidden">
			{@render children?.()}
		</main>
	</div>
</div>

<script lang="ts">
	import { theme } from '$lib/stores';
	import { Sun, Moon } from '@lucide/svelte';

	function toggle() {
		theme.update((t) => (t === 'dark' ? 'light' : 'dark'));
	}
</script>

<button
	onclick={toggle}
	class="relative inline-flex h-9 w-9 items-center justify-center rounded-xl text-gray-500 transition-colors hover:bg-surface-hover dark:text-gray-400 dark:hover:bg-dark-hover"
	aria-label="Přepnout režim"
>
	<Sun class="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
	<Moon class="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
</button>

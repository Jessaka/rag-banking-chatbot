<script lang="ts">
	import { cn } from '$lib/utils';
	import type { Snippet } from 'svelte';

	let {
		class: className = '',
		children,
		...rest
	}: {
		class?: string;
		children?: Snippet;
	} & Record<string, unknown> = $props();
</script>

<div class={cn('rounded-2xl border bg-white dark:bg-dark-surface dark:border-dark-border shadow-sm', className)} {...rest}>
	{@render children?.()}
</div>

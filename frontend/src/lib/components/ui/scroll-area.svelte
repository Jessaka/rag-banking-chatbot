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

<div class={cn('overflow-y-auto', className)} {...rest}>
	{@render children?.()}
</div>

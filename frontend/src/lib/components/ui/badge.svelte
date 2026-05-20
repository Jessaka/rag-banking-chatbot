<script lang="ts">
	import { cn } from '$lib/utils';
	import type { Snippet } from 'svelte';

	let {
		variant = 'default',
		class: className = '',
		children,
		...rest
	}: {
		variant?: 'default' | 'secondary' | 'outline' | 'success' | 'warning';
		class?: string;
		children?: Snippet;
	} & import('svelte/elements').HTMLSpanAttributes = $props();
</script>

<span
	class={cn(
		'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
		{
			'bg-rb-100 text-rb-800 dark:bg-rb-900/30 dark:text-rb-300': variant === 'default',
			'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300': variant === 'secondary',
			'border border-surface-border text-gray-600 dark:border-dark-border dark:text-gray-400':
				variant === 'outline',
			'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400':
				variant === 'success',
			'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400':
				variant === 'warning'
		},
		className
	)}
	{...rest}
>
	{@render children?.()}
</span>

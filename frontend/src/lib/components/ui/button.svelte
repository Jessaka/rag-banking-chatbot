<script lang="ts">
	import { cn } from '$lib/utils';
	import type { Snippet } from 'svelte';

	let {
		ref = $bindable(null),
		variant = 'default',
		size = 'default',
		disabled = false,
		class: className = '',
		children,
		onclick,
		...rest
	}: {
		ref?: HTMLButtonElement | null;
		variant?: 'default' | 'secondary' | 'ghost' | 'outline' | 'link' | 'icon';
		size?: 'default' | 'sm' | 'lg' | 'icon';
		disabled?: boolean;
		class?: string;
		children?: Snippet;
		onclick?: (e: MouseEvent) => void;
	} & Omit<import('svelte/elements').HTMLButtonAttributes, 'children' | 'class' | 'onclick'> = $props();
</script>

<button
	bind:this={ref}
	{disabled}
	{onclick}
	class={cn(
		'inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rb-400 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 select-none',
		{
			'bg-gray-900 text-white hover:bg-gray-800 dark:bg-dark-text dark:text-dark-bg dark:hover:bg-gray-200':
				variant === 'default',
			'bg-surface-alt text-gray-900 hover:bg-surface-hover dark:bg-dark-elevated dark:text-dark-text dark:hover:bg-dark-hover':
				variant === 'secondary',
			'hover:bg-surface-hover text-gray-700 dark:text-gray-300 dark:hover:bg-dark-hover':
				variant === 'ghost',
			'border border-surface-border bg-transparent hover:bg-surface-hover dark:border-dark-border dark:hover:bg-dark-hover':
				variant === 'outline',
			'text-rb-600 dark:text-rb-400 hover:underline underline-offset-4': variant === 'link'
		},
		{
			'h-10 px-4 py-2': size === 'default',
			'h-9 rounded-lg px-3 text-xs': size === 'sm',
			'h-11 rounded-xl px-6': size === 'lg',
			'h-10 w-10': size === 'icon'
		},
		className
	)}
	{...rest}
>
	{@render children?.()}
</button>

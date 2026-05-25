<script lang="ts">
	import { cn } from '$lib/utils';

	let {
		orientation = 'horizontal',
		class: className = '',
		...rest
	}: {
		orientation?: 'horizontal' | 'vertical';
		class?: string;
	} & Record<string, unknown> = $props();
</script>

<hr
	class={cn(
		'shrink-0 bg-surface-border dark:bg-dark-border',
		orientation === 'horizontal' ? 'h-[1px] w-full' : 'h-full w-[1px]',
		className
	)}
	{...rest}
/>

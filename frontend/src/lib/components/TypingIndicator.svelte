<script lang="ts">
	let { label = 'AI připravuje odpověď…' }: { label?: string } = $props();
</script>

<div class="flex items-center gap-2 text-sm text-gray-400 dark:text-gray-500 animate-fade-in" aria-live="polite">
	<div class="flex items-center gap-1">
		<span class="h-2 w-2 animate-pulse-dot rounded-full bg-rb-400"></span>
		<span class="h-2 w-2 animate-pulse-dot rounded-full bg-rb-400" style="animation-delay: 0.2s"></span>
		<span class="h-2 w-2 animate-pulse-dot rounded-full bg-rb-400" style="animation-delay: 0.4s"></span>
	</div>
	<span>{label}</span>
</div>

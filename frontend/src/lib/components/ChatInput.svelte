<script lang="ts">
	import { ArrowUp, Loader2 } from '@lucide/svelte';
	import { cn } from '$lib/utils';

	let {
		disabled = false,
		onsubmit
	}: {
		disabled?: boolean;
		onsubmit: (text: string) => void;
	} = $props();

	let text = $state('');
	let inputRef: HTMLTextAreaElement | null = $state(null);

	function handleSubmit() {
		const trimmed = text.trim();
		if (!trimmed || disabled) return;
		onsubmit(trimmed);
		text = '';
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSubmit();
		}
	}

	function autoResize() {
		if (inputRef) {
			inputRef.style.height = 'auto';
			inputRef.style.height = Math.min(inputRef.scrollHeight, 200) + 'px';
		}
	}

	$effect(() => {
		autoResize();
	});
</script>

<form
	onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}
	class="relative"
>
	<div
		class={cn(
			'flex items-end gap-2 rounded-2xl border bg-white px-4 py-3 transition-all duration-200',
			'focus-within:border-rb-400 focus-within:ring-1 focus-within:ring-rb-400/30',
			'dark:bg-dark-surface dark:border-dark-border',
			'disabled:opacity-50',
			disabled && 'opacity-50 pointer-events-none'
		)}
	>
		<textarea
			bind:this={inputRef}
			bind:value={text}
			onkeydown={handleKeydown}
			oninput={autoResize}
			placeholder={disabled ? 'Čekám na odpověď…' : 'Zeptejte se na bankovní produkty, poplatky...'}
			rows={1}
			disabled={disabled}
			class="flex-1 resize-none bg-transparent text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none dark:text-dark-text dark:placeholder:text-gray-500"
		></textarea>

		<button
			type="submit"
			disabled={!text.trim() || disabled}
			aria-label={disabled ? 'Odpověď se připravuje' : 'Odeslat zprávu'}
			class={cn(
				'flex h-8 w-8 shrink-0 items-center justify-center rounded-xl transition-all duration-200',
				text.trim() && !disabled
					? 'bg-gray-900 text-white hover:bg-gray-800 dark:bg-dark-text dark:text-dark-bg dark:hover:bg-gray-200'
					: 'bg-gray-100 text-gray-400 dark:bg-dark-elevated dark:text-gray-500'
			)}
		>
			{#if disabled}
				<Loader2 class="h-4 w-4 animate-spin" />
			{:else}
				<ArrowUp class="h-4 w-4" />
			{/if}
		</button>
	</div>
	<p class="mt-1.5 text-center text-[10px] text-gray-400 dark:text-gray-600">
		Enter pro odeslání · Shift+Enter pro nový řádek
	</p>
</form>

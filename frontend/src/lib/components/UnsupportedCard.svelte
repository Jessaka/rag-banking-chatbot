<script lang="ts">
	import { AlertTriangle } from '@lucide/svelte';
	import Markdown from './Markdown.svelte';
	import EscalationCTA from './EscalationCTA.svelte';

	let {
		content = '',
		reason = null,
		onask
	}: {
		content?: string;
		reason?: string | null;
		onask?: (value: string) => void;
	} = $props();

	function reasonCopy(value?: string | null) {
		if (value === 'unsupported_crypto') return 'Téma je mimo spolehlivý rozsah znalostí tohoto asistenta.';
		if (value === 'no_retrieval_sources') return 'Nepodařilo se najít dostatečné podklady v dostupných zdrojích RB.';
		return 'U této odpovědi je vhodné ověření přímo u RB.';
	}
</script>

<div class="rounded-2xl border border-amber-200 bg-amber-50/70 p-4 dark:border-amber-900/40 dark:bg-amber-900/10">
	<div class="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
		<AlertTriangle class="h-4 w-4" />
		Tady si nejsem jistý
	</div>
	<p class="mb-3 text-xs text-amber-700 dark:text-amber-300">{reasonCopy(reason)}</p>
	<div class="prose-custom">
		<Markdown {content} />
	</div>
	<div class="mt-3">
		<EscalationCTA variant="unsupported" {onask} />
	</div>
</div>

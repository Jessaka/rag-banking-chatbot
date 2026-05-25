<script lang="ts">
	import { ShieldCheck } from '@lucide/svelte';
	import Markdown from './Markdown.svelte';
	import EscalationCTA from './EscalationCTA.svelte';

	let { content = '', onask }: { content?: string; onask?: (value: string) => void } = $props();
</script>

<div class="rounded-2xl border border-rb-200 bg-rb-50/70 p-4 dark:border-rb-900/40 dark:bg-rb-900/10">
	<div class="mb-3 flex items-center gap-2 text-sm font-semibold text-rb-800 dark:text-rb-300">
		<ShieldCheck class="h-4 w-4" />
		Doporučený postup
	</div>
	<div class="prose-custom">
		<Markdown {content} />
	</div>
	<div class="mt-3">
		<EscalationCTA variant="guided-flow" {onask} />
	</div>
</div>

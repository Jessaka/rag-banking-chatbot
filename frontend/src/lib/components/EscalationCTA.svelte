<script lang="ts">
	import { PhoneCall } from '@lucide/svelte';
	import { emitChatEvent } from '$lib/monitoring';

	let {
		variant = 'default',
		onask
	}: {
		variant?: 'default' | 'guided-flow' | 'unsupported' | 'low-confidence' | 'clarify';
		onask?: (value: string) => void;
	} = $props();

	function ask(text: string) {
		emitChatEvent('chat_escalation_clicked', { variant, text });
		onask?.(text);
	}
</script>

<div class="flex flex-col gap-2 rounded-xl bg-white/70 p-3 text-xs dark:bg-dark-elevated/70 sm:flex-row sm:items-center sm:justify-between">
	<div class="flex items-start gap-2 text-gray-600 dark:text-gray-300">
		<PhoneCall class="mt-0.5 h-4 w-4 text-rb-500" />
		<span>U důležitých nebo citlivých úkonů doporučujeme ověřit postup přímo u Raiffeisenbank.</span>
	</div>
</div>

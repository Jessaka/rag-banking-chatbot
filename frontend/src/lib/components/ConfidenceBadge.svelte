<script lang="ts">
	import type { ConfidenceBucket } from '$lib/types';
	import { confidenceLabel, confidenceTone, userConfidenceReason } from '$lib/chat-ux';
	import { Badge } from '$ui';

	let {
		bucket = null,
		reason = null
	}: {
		bucket?: ConfidenceBucket | null;
		reason?: string | null;
	} = $props();
</script>

{#if bucket}
	<div class="flex flex-wrap items-center gap-2">
		<Badge variant={confidenceTone(bucket)}>{confidenceLabel(bucket)}</Badge>
		<span class="text-xs text-gray-500 dark:text-gray-400">{userConfidenceReason(reason)}</span>
	</div>
{/if}

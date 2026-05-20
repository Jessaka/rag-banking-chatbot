<script lang="ts">
	import { marked } from 'marked';

	let { content = '', class: className = '' }: { content?: string; class?: string } = $props();

	$effect(() => {
		// Configure marked once
		marked.setOptions({
			gfm: true,
			breaks: false
		});
	});

	let html = $derived.by(() => {
		if (!content) return '';
		return marked.parse(content, { async: false }) as string;
	});
</script>

{#if html}
	<div class="prose-custom {className}">
		{@html html}
	</div>
{/if}

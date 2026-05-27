<script lang="ts">
	import { page } from '$app/stores';
	import { debugPanelOpen } from '$lib/stores';
	import { formatTime } from '$lib/utils';
	import { ChevronDown, ChevronUp, Bug, Clock } from '@lucide/svelte';
	import { Badge } from '$ui';

 type DebugSource = {
		file_name: string;
		page: number | null;
		rerank_score: number | null;
		human_title?: string | null;
		why_this_source?: string | null;
		trust_score?: number | null;
		authority_weight?: number | null;
		recency_weight?: number | null;
		stability_weight?: number | null;
		authority_tier?: string | null;
	};

	type RetrievalDebugRow = Record<string, unknown>;

	let {
		strategy = null,
		confidence = null,
		latency = null as number | null,
		retrieval_latency = null as number | null,
		llm_latency = null as number | null,
		formatting_latency = null as number | null,
		debug = null as unknown | null,
		sources = [] as DebugSource[],
		// Priority 2: Confidence semantics
		confidenceSemanticLabel = null as string | null,
		confidenceOrigin = null as string | null,
		confidenceOriginLabel = null as string | null,
		confidenceReason = null as string | null,
		degraded = null as boolean | null,
		request_id = null as string | null,
		streamed = null as boolean | null,
	}: {
		strategy?: string | null;
		confidence?: string | null;
		latency?: number | null;
		retrieval_latency?: number | null;
		llm_latency?: number | null;
		formatting_latency?: number | null;
		debug?: unknown | null;
		sources?: DebugSource[];
		confidenceSemanticLabel?: string | null;
		confidenceOrigin?: string | null;
		confidenceOriginLabel?: string | null;
		confidenceReason?: string | null;
		degraded?: boolean | null;
		request_id?: string | null;
		streamed?: boolean | null;
	} = $props();

	let isOpen = $state(false);
	const debugMode = $derived($page.url.searchParams.has('debug'));
	const debugRecord = $derived(
		debug && typeof debug === 'object' ? (debug as Record<string, unknown>) : null
	);
	const debugRows = $derived(
		Array.isArray(debug)
			? (debug.filter((row) => row && typeof row === 'object') as RetrievalDebugRow[])
			: debugRecord
				? [debugRecord]
				: []
	);
	const firstDebugRow = $derived(debugRows.length > 0 ? debugRows[0] : null);
	const streamingState = $derived(
		streamed ??
			(typeof debugRecord?.streamed === 'boolean'
				? debugRecord.streamed
				: typeof debugRecord?.used_streaming === 'boolean'
					? debugRecord.used_streaming
					: null)
	);
	const sessionContextUsed = $derived(debugRecord?.session_context_used === true);
	const inheritedProduct = $derived(
		typeof debugRecord?.inherited_product === 'string' ? debugRecord.inherited_product : null
	);
	const inheritedIntent = $derived(
		typeof debugRecord?.inherited_intent === 'string' ? debugRecord.inherited_intent : null
	);
	const telemetryRequestId = $derived(
		request_id ?? (typeof debugRecord?.request_id === 'string' ? debugRecord.request_id : null)
	);
	const recoveryPassUsed = $derived(firstDebugRow?.recovery_pass_used === true);
	const suppressedCount = $derived(
		typeof firstDebugRow?.governance_suppressed_count === 'number'
			? firstDebugRow.governance_suppressed_count
			: typeof firstDebugRow?.governance_removed_count === 'number'
				? firstDebugRow.governance_removed_count
				: null
	);
	const diversityScore = $derived(
		typeof firstDebugRow?.diversity_score === 'number'
			? firstDebugRow.diversity_score
			: typeof firstDebugRow?.source_diversity_score === 'number'
				? firstDebugRow.source_diversity_score
				: null
	);
	const collapseDetected = $derived(firstDebugRow?.retrieval_collapse_detected === true);
	const resilienceStrategy = $derived(
		typeof firstDebugRow?.resilience_strategy === 'string' ? firstDebugRow.resilience_strategy : null
	);
	const pricingCanonicalSource = $derived(
		typeof firstDebugRow?.pricing_canonical_source === 'string' ? firstDebugRow.pricing_canonical_source : null
	);
	const pricingConfidence = $derived(
		typeof firstDebugRow?.pricing_confidence === 'string' ? firstDebugRow.pricing_confidence : null
	);
	const pricingSourceType = $derived(
		typeof firstDebugRow?.pricing_source_type === 'string' ? firstDebugRow.pricing_source_type : null
	);
	const normalizedPrice = $derived(firstDebugRow?.normalized_price ?? null);
	const conditionalPricingDetected = $derived(firstDebugRow?.conditional_pricing_detected === true);
	const conditionType = $derived(
		typeof firstDebugRow?.condition_type === 'string' ? firstDebugRow.condition_type : null
	);
	const conditionText = $derived(
		typeof firstDebugRow?.condition_text === 'string' ? firstDebugRow.condition_text : null
	);
	const basePrice = $derived(firstDebugRow?.base_price ?? null);
	const conditionalPrice = $derived(firstDebugRow?.conditional_price ?? null);
	const pricingLogic = $derived(
		typeof firstDebugRow?.pricing_logic === 'string' ? firstDebugRow.pricing_logic : null
	);
	const pricingRowFound = $derived(
		typeof firstDebugRow?.pricing_row_found === 'boolean' ? firstDebugRow.pricing_row_found : null
	);
	const pricingCanonicalUsed = $derived(firstDebugRow?.pricing_canonical_used === true);
	const extractedPricingRow = $derived(
		firstDebugRow?.extracted_pricing_row && typeof firstDebugRow.extracted_pricing_row === 'object'
			? firstDebugRow.extracted_pricing_row
			: null
	);

	$effect(() => {
		isOpen = $debugPanelOpen;
	});

	function toggle() {
		isOpen = !isOpen;
		debugPanelOpen.set(isOpen);
	}

	function formatScore(value: number | null | undefined, digits = 3) {
		return value != null ? value.toFixed(digits) : '—';
	}

	function getTrustTone(score: number | null | undefined) {
		if (score == null) return 'bg-gray-400 text-gray-500 dark:text-gray-400';
		if (score >= 0.75) return 'bg-green-500 text-green-700 dark:text-green-400';
		if (score >= 0.5) return 'bg-yellow-500 text-yellow-700 dark:text-yellow-400';
		return 'bg-red-500 text-red-700 dark:text-red-400';
	}
</script>

{#if debugMode}
	<div class="rounded-2xl border bg-white dark:bg-dark-surface dark:border-dark-border overflow-hidden transition-all">
		<button
			onclick={toggle}
			class="flex w-full items-center justify-between px-4 py-3 text-sm transition-colors hover:bg-surface-hover dark:hover:bg-dark-hover"
		>
			<span class="flex items-center gap-2 font-medium text-gray-700 dark:text-gray-300">
				<Bug class="h-4 w-4 text-gray-400" />
				Debug (debug)
			</span>
			{#if isOpen}
				<ChevronUp class="h-4 w-4 text-gray-400" />
			{:else}
				<ChevronDown class="h-4 w-4 text-gray-400" />
			{/if}
		</button>

		{#if isOpen && strategy}
			<div class="border-t px-4 py-3 space-y-3 dark:border-dark-border">
				<div class="flex flex-wrap items-center gap-2">
					{#if strategy}
						<Badge variant={strategy === 'pricing_row_direct' ? 'success' : 'default'}>
							{strategy}
						</Badge>
					{/if}
					{#if confidence}
						<Badge variant={confidence === 'high' ? 'success' : 'warning'}>
							{confidence}
						</Badge>
					{/if}
					{#if latency != null}
						<span class="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
							<Clock class="h-3 w-3" />
							{formatTime(latency)}
						</span>
					{/if}
				</div>

				<div>
					<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Telemetry</p>
					<div class="space-y-1">
						<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
							<span class="text-gray-600 dark:text-gray-400">Streaming state</span>
							<span class="font-mono text-gray-700 dark:text-gray-300">
								{streamingState == null ? 'Unknown' : streamingState ? 'Streamed' : 'Not streamed'}
							</span>
						</div>
						{#if telemetryRequestId}
							<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
								<span class="text-gray-600 dark:text-gray-400">Request ID</span>
								<span class="ml-3 truncate font-mono text-gray-700 dark:text-gray-300">{telemetryRequestId}</span>
							</div>
						{/if}
					</div>
				</div>

				{#if recoveryPassUsed || suppressedCount != null || diversityScore != null || collapseDetected || resilienceStrategy}
					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Retrieval resilience</p>
						<div class="space-y-1">
							<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
								<span class="text-gray-600 dark:text-gray-400">Recovery pass</span>
								<span class="font-mono text-gray-700 dark:text-gray-300">{recoveryPassUsed ? 'Used' : 'Not used'}</span>
							</div>
							{#if suppressedCount != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Suppressed count</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{suppressedCount}</span>
								</div>
							{/if}
							{#if diversityScore != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Diversity score</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{formatScore(diversityScore)}</span>
								</div>
							{/if}
							<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
								<span class="text-gray-600 dark:text-gray-400">Collapse detection</span>
								<span class="font-mono text-gray-700 dark:text-gray-300">{collapseDetected ? 'Detected' : 'Clear'}</span>
							</div>
							{#if resilienceStrategy}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Strategy</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{resilienceStrategy}</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				{#if pricingCanonicalSource || pricingConfidence || pricingSourceType || normalizedPrice != null || conditionalPricingDetected || pricingRowFound != null || extractedPricingRow}
					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Canonical pricing resolver</p>
						<div class="space-y-1">
							{#if pricingCanonicalSource}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Canonical source</span>
									<span class="ml-3 truncate font-mono text-gray-700 dark:text-gray-300">{pricingCanonicalSource}</span>
								</div>
							{/if}
							{#if pricingConfidence}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Pricing confidence</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{pricingConfidence}</span>
								</div>
							{/if}
							{#if pricingSourceType}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Source type</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{pricingSourceType}</span>
								</div>
							{/if}
							{#if normalizedPrice != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Normalized price</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{String(normalizedPrice)}</span>
								</div>
							{/if}
							{#if conditionalPricingDetected}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Conditional pricing</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">Detected</span>
								</div>
							{/if}
							{#if conditionType}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Condition type</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{conditionType}</span>
								</div>
							{/if}
							{#if basePrice != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Base price</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{String(basePrice)}</span>
								</div>
							{/if}
							{#if conditionalPrice != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Conditional price</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{String(conditionalPrice)}</span>
								</div>
							{/if}
							{#if conditionText}
								<div class="rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<p class="mb-1 text-gray-600 dark:text-gray-400">Condition text</p>
									<p class="text-gray-700 dark:text-gray-300">{conditionText}</p>
								</div>
							{/if}
							{#if pricingLogic}
								<div class="rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<p class="mb-1 text-gray-600 dark:text-gray-400">Interpreted pricing logic</p>
									<p class="font-mono text-gray-700 dark:text-gray-300">{pricingLogic}</p>
								</div>
							{/if}
							{#if pricingRowFound != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Explicit row</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{pricingRowFound ? 'Found' : 'Missing'}</span>
								</div>
							{/if}
							<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
								<span class="text-gray-600 dark:text-gray-400">Canonical override</span>
								<span class="font-mono text-gray-700 dark:text-gray-300">{pricingCanonicalUsed ? 'Used' : 'Not used'}</span>
							</div>
							{#if extractedPricingRow}
								<details class="rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<summary class="cursor-pointer text-gray-600 dark:text-gray-400">Extracted pricing row</summary>
									<pre class="mt-1 max-h-32 overflow-auto text-[10px] text-gray-700 dark:text-gray-300"><code>{JSON.stringify(extractedPricingRow, null, 2)}</code></pre>
								</details>
							{/if}
						</div>
					</div>
				{/if}

				{#if confidenceSemanticLabel || confidenceOriginLabel || degraded != null}
					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Confidence semantics</p>
						<div class="space-y-1">
							{#if confidenceSemanticLabel}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Label</span>
									<span class="font-medium text-gray-700 dark:text-gray-300">{confidenceSemanticLabel}</span>
								</div>
							{/if}
							{#if confidenceOriginLabel}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Origin</span>
									<span class="text-gray-700 dark:text-gray-300">{confidenceOriginLabel}</span>
								</div>
							{/if}
							{#if degraded != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Degraded</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{degraded ? 'Yes' : 'No'}</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				{#if confidence || confidenceReason || confidenceOrigin || confidenceOriginLabel || confidenceSemanticLabel || degraded != null}
					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Full confidence origin</p>
						<div class="space-y-1">
							{#if confidence}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Bucket</span>
									<span class="text-gray-700 dark:text-gray-300">{confidence}</span>
								</div>
							{/if}
							{#if confidenceReason}
								<div class="rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<p class="mb-1 text-gray-600 dark:text-gray-400">Reason</p>
									<p class="text-gray-700 dark:text-gray-300">{confidenceReason}</p>
								</div>
							{/if}
							{#if confidenceOrigin}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Origin key</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{confidenceOrigin}</span>
								</div>
							{/if}
							{#if confidenceOriginLabel}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Origin label</span>
									<span class="text-gray-700 dark:text-gray-300">{confidenceOriginLabel}</span>
								</div>
							{/if}
							{#if confidenceSemanticLabel}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Semantic label</span>
									<span class="text-gray-700 dark:text-gray-300">{confidenceSemanticLabel}</span>
								</div>
							{/if}
							{#if degraded != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Degraded answer</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{degraded ? 'Yes' : 'No'}</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				{#if retrieval_latency != null || llm_latency != null || formatting_latency != null}
					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Timing breakdown</p>
						<div class="space-y-1">
							{#if retrieval_latency != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Retrieval</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{formatTime(retrieval_latency)}</span>
								</div>
							{/if}
							{#if llm_latency != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">LLM</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{formatTime(llm_latency)}</span>
								</div>
							{/if}
							{#if formatting_latency != null}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Formatting</span>
									<span class="font-mono text-gray-700 dark:text-gray-300">{formatTime(formatting_latency)}</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				{#if sessionContextUsed}
					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Session inheritance</p>
						<div class="space-y-1">
							<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
								<span class="text-gray-600 dark:text-gray-400">Session context used</span>
								<span class="font-mono text-gray-700 dark:text-gray-300">Yes</span>
							</div>
							{#if inheritedProduct}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Inherited product</span>
									<span class="text-gray-700 dark:text-gray-300">{inheritedProduct}</span>
								</div>
							{/if}
							{#if inheritedIntent}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="text-gray-600 dark:text-gray-400">Inherited intent</span>
									<span class="text-gray-700 dark:text-gray-300">{inheritedIntent}</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				{#if sources.length > 0}
					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Top zdroje</p>
						<div class="space-y-1">
							{#each sources.slice(0, 3) as src}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<span class="truncate text-gray-700 dark:text-gray-300">{src.human_title ?? src.file_name}</span>
									<span class="ml-2 shrink-0 text-gray-400">{src.rerank_score?.toFixed(3) ?? '—'}</span>
								</div>
							{/each}
						</div>
					</div>

					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Trust score summary</p>
						<div class="space-y-1">
							{#each sources as src}
								{@const trustTone = getTrustTone(src.trust_score)}
								<div class="flex items-center justify-between rounded-lg bg-surface-alt px-3 py-1.5 text-xs dark:bg-dark-elevated">
									<div class="flex min-w-0 items-center gap-2">
										<span class={`h-2.5 w-2.5 shrink-0 rounded-full ${trustTone.split(' ')[0]}`}></span>
										<span class="truncate text-gray-700 dark:text-gray-300">{src.human_title ?? src.file_name}</span>
									</div>
									<span class={`ml-2 shrink-0 font-mono ${trustTone.split(' ').slice(1).join(' ')}`}>
										{formatScore(src.trust_score)}
									</span>
								</div>
							{/each}
						</div>
					</div>

					<div>
						<p class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Source ranking scores</p>
						<div class="space-y-2">
							{#each sources as src}
								<div class="rounded-lg bg-surface-alt px-3 py-2 text-xs dark:bg-dark-elevated">
									<p class="truncate font-medium text-gray-700 dark:text-gray-300">{src.human_title ?? src.file_name}</p>
									<div class="mt-2 grid gap-1 sm:grid-cols-2">
										<div class="flex items-center justify-between gap-3"><span class="text-gray-600 dark:text-gray-400">rerank_score</span><span class="font-mono text-gray-700 dark:text-gray-300">{formatScore(src.rerank_score)}</span></div>
										<div class="flex items-center justify-between gap-3"><span class="text-gray-600 dark:text-gray-400">trust_score</span><span class="font-mono text-gray-700 dark:text-gray-300">{formatScore(src.trust_score)}</span></div>
										<div class="flex items-center justify-between gap-3"><span class="text-gray-600 dark:text-gray-400">authority_weight</span><span class="font-mono text-gray-700 dark:text-gray-300">{formatScore(src.authority_weight)}</span></div>
										<div class="flex items-center justify-between gap-3"><span class="text-gray-600 dark:text-gray-400">recency_weight</span><span class="font-mono text-gray-700 dark:text-gray-300">{formatScore(src.recency_weight)}</span></div>
										<div class="flex items-center justify-between gap-3"><span class="text-gray-600 dark:text-gray-400">stability_weight</span><span class="font-mono text-gray-700 dark:text-gray-300">{formatScore(src.stability_weight)}</span></div>
										<div class="flex items-center justify-between gap-3"><span class="text-gray-600 dark:text-gray-400">authority_tier</span><span class="font-mono text-gray-700 dark:text-gray-300">{src.authority_tier ?? '—'}</span></div>
									</div>
									{#if src.why_this_source}
										<div class="mt-2 border-t border-gray-200 pt-2 dark:border-dark-border">
											<p class="mb-1 text-gray-600 dark:text-gray-400">why_this_source</p>
											<p class="text-gray-700 dark:text-gray-300">{src.why_this_source}</p>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if debug}
					<details class="group">
						<summary class="cursor-pointer text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
							Raw retrieval debug
						</summary>
						<pre class="mt-1.5 max-h-48 overflow-auto rounded-lg bg-gray-50 p-2 text-[10px] leading-relaxed text-gray-600 dark:bg-dark-elevated dark:text-gray-400"><code>{JSON.stringify(debug, null, 2)}</code></pre>
					</details>
				{/if}
			</div>
		{/if}
	</div>
{/if}

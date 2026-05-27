export interface ChatRequest {
	question: string;
	session_id?: string | null;
}

export interface SourceDocument {
	file_name: string;
	page: number | null;
	chunk_id: string | null;
	rerank_score: number | null;
	preview: string;

	// Priority 2: Source UX metadata
	human_title?: string | null;
	display_url?: string | null;
	source_year?: number | null;
	current_or_archived?: string | null;
	source_category?: string | null;
	source_label?: string | null;
	// Priority 3: Retrieval observability
	why_this_source?: string | null;
	// Priority 5: Source UX refinement
	source_context_label?: string | null;
	source_relevance_reason?: string | null;
	// Priority 2b: Source trust scoring
	trust_score?: number | null;
	authority_weight?: number | null;
	recency_weight?: number | null;
	stability_weight?: number | null;
	authority_tier?: string | null;
	// Priority 1b: Source freshness governance
	source_freshness_bucket?: string | null;
	freshness_priority_score?: number | null;
	stale_source_suppressed?: boolean | null;
	effective_date?: string | null;
	valid_from?: string | null;
	valid_to?: string | null;
	freshness_reason?: string | null;
	// Priority 4: Retrieval explainability
	retrieval_reason?: string | null;
	authority_reason?: string | null;
}

export type ConfidenceBucket = 'high' | 'medium' | 'low';

export interface ChatResponse {
	answer: string;
	sources: SourceDocument[];
	session_id: string;
	processing_time_ms: number;
	request_id: string | null;
	answer_strategy: string | null;
	confidence_bucket: ConfidenceBucket | null;
	confidence_reason: string | null;
	clarification_required: boolean | null;
	unsupported_reason: string | null;
	error: string | null;
	traceback: string | null;
	retrieval_debug: unknown | null;
	// Priority 5: Latency observability
	cache_check_ms?: number | null;
	retrieval_latency_ms?: number | null;
	llm_latency_ms?: number | null;
	formatting_latency_ms?: number | null;
	// Priority 2: Confidence semantics
	confidence_origin?: string | null;
	confidence_origin_label?: string | null;
	confidence_semantic_label?: string | null;
	degraded_answer?: boolean | null;
}

export interface Message {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	timestamp: number;
	sources?: SourceDocument[];
	retrieval_debug?: unknown | null;
	answer_strategy?: string | null;
	confidence_bucket?: ConfidenceBucket | null;
	confidence_reason?: string | null;
	clarification_required?: boolean | null;
	unsupported_reason?: string | null;
	processing_time_ms?: number;
	request_id?: string | null;
	error?: boolean;
	// Priority 5: Latency observability
	retrieval_latency_ms?: number | null;
	llm_latency_ms?: number | null;
	formatting_latency_ms?: number | null;
	// Priority 2: Confidence semantics
	confidence_origin?: string | null;
	confidence_origin_label?: string | null;
	confidence_semantic_label?: string | null;
	degraded_answer?: boolean | null;
}

export interface Conversation {
	id: string;
	title: string;
	messages: Message[];
	createdAt: number;
	updatedAt: number;
}

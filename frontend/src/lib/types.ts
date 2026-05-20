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
}

export interface ChatResponse {
	answer: string;
	sources: SourceDocument[];
	session_id: string;
	processing_time_ms: number;
	request_id: string | null;
	answer_strategy: string | null;
	answer_confidence?: string | null;
	error: string | null;
	traceback: string | null;
	retrieval_debug: unknown | null;
}

export interface Message {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	timestamp: number;
	sources?: SourceDocument[];
	retrieval_debug?: unknown | null;
	answer_strategy?: string | null;
	answer_confidence?: string | null;
	processing_time_ms?: number;
	error?: boolean;
}

export interface Conversation {
	id: string;
	title: string;
	messages: Message[];
	createdAt: number;
	updatedAt: number;
}

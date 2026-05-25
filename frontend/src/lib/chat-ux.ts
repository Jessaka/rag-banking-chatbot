import type { ConfidenceBucket, Message, SourceDocument } from './types';

export function confidenceLabel(bucket?: ConfidenceBucket | null): string {
	if (bucket === 'high') return 'Ověřeno ve zdrojích RB';
	if (bucket === 'medium') return 'Doporučená odpověď';
	if (bucket === 'low') return 'Vyžaduje ověření';
	return 'Bez hodnocení jistoty';
}

export function confidenceTone(bucket?: ConfidenceBucket | null): 'success' | 'warning' | 'outline' {
	if (bucket === 'high') return 'success';
	if (bucket === 'medium') return 'warning';
	return 'outline';
}

export function userConfidenceReason(reason?: string | null): string {
	const value = (reason || '').toLowerCase();
	if (value.includes('validated structured pricing row')) return 'Odpověď vychází z konkrétního ceníku.';
	if (value.includes('pricing') || value.includes('source-backed')) return 'Odpověď vychází z nalezených podkladů RB.';
	if (value.includes('clarification')) return 'Potřebuji upřesnit, co přesně myslíte.';
	if (value.includes('unsupported')) return 'Téma je mimo spolehlivý rozsah tohoto asistenta.';
	if (value.includes('guided flow')) return 'Jde o doporučený postup pro danou situaci.';
	if (value.includes('identity')) return 'Toto je systémová odpověď asistenta.';
	return 'Doporučujeme odpověď ověřit podle oficiálních podkladů RB.';
}

export function isGuidedFlow(message: Message): boolean {
	return message.answer_strategy === 'guided_flow_direct';
}

export function isUnsupported(message: Message): boolean {
	return Boolean(message.unsupported_reason) || message.answer_strategy === 'unsupported_direct' || message.answer_strategy === 'fallback_no_answer';
}

export function shouldShowEscalation(message: Message): boolean {
	return isUnsupported(message) || isGuidedFlow(message) || message.confidence_bucket === 'low';
}

export function clarificationOptions(message: Message): string[] {
	if (!message.clarification_required) return [];
	const text = message.content.toLowerCase();
	const options: string[] = [];
	if (text.includes('osobní') || text.includes('osobni')) options.push('osobní');
	if (text.includes('podnikatelské') || text.includes('podnikatelske')) options.push('podnikatelské');
	if (text.includes('firemní') || text.includes('firemni')) options.push('firemní');
	if (text.includes('debetní') || text.includes('debetni')) options.push('debetní karta');
	if (text.includes('kreditní') || text.includes('kreditni')) options.push('kreditní karta');
	return [...new Set(options)].slice(0, 4);
}

export function sourceRationale(source: SourceDocument, strategy?: string | null): string {
	if (strategy === 'pricing_row_direct') return 'Tento zdroj obsahuje konkrétní ceníkový řádek použitý v odpovědi.';
	if (source.file_name?.toLowerCase().includes('faq')) return 'Tato FAQ položka odpovídá tématu vašeho dotazu.';
	return 'Tento zdroj obsahuje pasáž, ze které odpověď vychází.';
}

export function sourceType(source: SourceDocument): string {
	const name = source.file_name.toLowerCase();
	if (name.includes('cenik') || name.includes('ceník')) return 'Ceník / podmínky';
	if (name.endsWith('.pdf') || name.includes('.pdf')) return 'PDF dokument';
	if (name.includes('faq')) return 'FAQ';
	return 'Zdroj RB';
}

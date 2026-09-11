"""Bounded, deterministic planning for multi-source historical retrieval."""
from dataclasses import asdict, dataclass, field
import re


GENERIC = set('What Why How When Where Who Which Compare Explain Describe Tell Give In On At Did Does Do Was Were Is Are The A An His Her Their After Before Year'.split())
GENERIC_PHRASES = {
    'politics', 'institutions', 'social conflict', 'economic conditions',
    'military change', 'civil war', 'causes', 'consequences', 'aftermath',
    'war', 'revolution', 'republic', 'empire', 'history', 'the',
}


@dataclass(frozen=True)
class HistoricalEntity:
    display_name: str
    normalized_name: str
    entity_type: str
    aliases: tuple = ()
    confidence: float = .7
    reason: str = 'question'

    def to_dict(self):
        value = asdict(self)
        value['aliases'] = list(self.aliases)
        return value


@dataclass(frozen=True)
class RetrievalPlan:
    schema_version: int
    resolved_question: str
    intent: str
    breadth: str
    seed_queries: tuple
    entities: tuple = field(default_factory=tuple)
    date_or_period_hints: tuple = field(default_factory=tuple)
    article_limit: int = 3

    def to_dict(self):
        value = asdict(self)
        value['seed_queries'] = list(self.seed_queries)
        value['entities'] = [entity.to_dict() for entity in self.entities]
        value['date_or_period_hints'] = list(self.date_or_period_hints)
        return value


def normalize_entity(value):
    value = value.replace('_', ' ').replace('\u2019', "'")
    value = re.sub(r'\s*\([^)]{1,60}\)\s*$', '', value)
    value = re.sub(r'[^\w\-\' ]+', ' ', value, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', value).strip().casefold()


def _entity_type(name, question):
    low = name.casefold()
    context = question.casefold()
    if re.search(r'\b(treaty|law|act|constitution|republic|parliament|congress|institution|carta)\b', low):
        return 'institution_or_settlement'
    if re.search(r'\b(war|revolution|battle|crisis|revolt|uprising|assassination)\b', low):
        return 'event'
    if re.search(r'\b(empire|republic|kingdom|state|country|france|russia|haiti|bohemia|serbia)\b', low):
        return 'state_or_place'
    if re.search(r'\b(party|movement|church|army|alliance|organization)\b', low):
        return 'organization'
    if re.search(r'\b(archduke|king|queen|emperor|president|general|saint)\b', low) or name.count(' ') >= 1:
        return 'person_or_named_subject'
    if re.search(r'\b(he|him|his|she|her)\b', context):
        return 'person_or_named_subject'
    return 'named_subject'


def extract_entities(question, prior_entities=(), limit=8):
    """Extract conservative named subjects; output is stable and safe for local lookup."""
    if limit < 1:
        return []
    candidates = []
    # Capitalized runs cover named people, states, events and settlements without
    # treating ordinary nouns as entities. Slashes represent alternate surface forms.
    pattern = r"\b(?:[A-Z][\w'\u2019-]*)(?:\s+(?:of|the|and|de|von|[A-Z][\w'\u2019-]*)){0,6}"
    for match in re.finditer(pattern, question):
        value = match.group().strip()
        words = value.split()
        while words and words[0] in GENERIC:
            words.pop(0)
        value = ' '.join(words).strip()
        if value:
            candidates.append((value, 'question', .82))
    paired = re.search(r'\b([A-Z][\w\'-]+)\s+and\s+([A-Z][\w\'-]+)\s+(Revolutions|Wars|Empires|Republics|Kingdoms)\b', question)
    if paired:
        suffix = paired.group(3)[:-1]
        candidates.extend(((paired.group(1) + ' ' + suffix, 'comparison subject', .9),
                           (paired.group(2) + ' ' + suffix, 'comparison subject', .9)))
    for side in re.split(r'[/;]', question):
        side = side.strip(' ?!.,')
        if 1 <= len(side.split()) <= 5 and side and side[0].isupper():
            candidates.append((side, 'question variant', .72))
    # Bounded conversation entities are used only for genuinely contextual questions.
    if re.search(r'\b(he|him|his|she|her|it|its|they|their|the republic|afterward)\b', question, re.I):
        candidates.extend((str(value), 'bounded conversation', .68) for value in prior_entities[:3])
    entities, seen = [], set()
    for display, reason, confidence in candidates:
        if paired and reason == 'question' and normalize_entity(display) == normalize_entity(paired.group(0)):
            continue
        normalized = normalize_entity(display)
        if not normalized or normalized in GENERIC_PHRASES or normalized in seen or len(normalized) < 3:
            continue
        seen.add(normalized)
        aliases = []
        if '&' in display:
            aliases.append(display.replace('&', 'and'))
        entities.append(HistoricalEntity(display, normalized, _entity_type(display, question),
                                         tuple(aliases), confidence, reason))
        if len(entities) == limit:
            break
    return entities


def _subject(question):
    cleaned = re.sub(r'^(?:what caused|why did|how did|in what year was|what|why|how|when|where|who|which|compare|explain|describe|tell me about)\s+', '', question, flags=re.I)
    return cleaned.strip(' ?!.,')[:220]


def build_plan(analysis, config, state=None):
    resolved = analysis.retrieval_query.strip()
    broad = analysis.effective_type in ('cause', 'comparison', 'timeline') or bool(
        re.search(r'\b(reshape|consequences?|effects?|affect|reforms?|spread|several|multiple|relationship|instability)\b', resolved, re.I))
    breadth = 'broad' if broad else 'narrow'
    subject = _subject(analysis.question)
    prior = getattr(state, 'entities', []) if state is not None else []
    entities = extract_entities(analysis.question, prior, config.max_entities)
    queries = [resolved]
    if analysis.effective_type == 'cause':
        queries.extend((f'{subject} political institutions causes',
                        f'{subject} social economic conflict',
                        f'{subject} military change civil war escalation'))
    elif analysis.effective_type == 'comparison':
        subjects = [entity.display_name for entity in entities if entity.reason == 'comparison subject']
        core = re.sub(r'^compare\s+', '', subject, flags=re.I)
        sides = subjects or [s.strip(' ?!.,') for s in re.split(r'\s+(?:and|versus|vs\.?)\s+', core, maxsplit=1, flags=re.I)]
        queries.extend(f'{side} causes political social economic military' for side in sides if side)
    elif broad:
        queries.extend((f'{subject} consequences political social', f'{subject} international actors chronology'))
    queries = list(dict.fromkeys(q for q in queries if q.strip()))[:config.max_seed_queries]
    dates = tuple(dict.fromkeys(re.findall(r'\b(?:c\.?\s*)?\d{3,4}(?:\s*(?:BCE|BC|CE|AD))?\b', resolved, re.I)))[:config.max_date_hints]
    article_limit = config.candidate_articles if broad else min(config.narrow_candidate_articles, config.candidate_articles)
    return RetrievalPlan(1, resolved, analysis.effective_type, breadth, tuple(queries),
                         tuple(entities), dates, article_limit)

"""Small rule-based intent detector and bounded contextual query interpretation."""
from dataclasses import dataclass, asdict
import re


@dataclass
class QueryAnalysis:
    question: str
    retrieval_query: str
    question_type: str
    effective_type: str
    is_followup: bool = False
    clarification: str = ''
    context_summary: str = ''
    anchor_year: int = None

    def to_dict(self):
        return asdict(self)


def detect_type(question):
    q = question.lower()
    if re.search(r'\b(timeline|chronolog\w*)\b|when did .*events|what happened between|what happened (?:next|after)', q):
        return 'timeline'
    if re.search(r'\b(compar\w*|versus|vs\.?|differences?|similarities?|differ)\b', q):
        return 'comparison'
    if re.search(r'\b(why|caus\w*|explain|explanation|reason\w*|lead to|led to|contribut\w*|collapse\w*|immediate|mattered)\b', q):
        return 'cause'
    if re.search(r'^(who|where|what) (?:was|were|is|are)\b|^tell me about\b', q):
        return 'lookup'
    return 'general'


def contextual(question):
    q = question.lower().strip()
    return bool(re.search(r'\b(that|those|these|it|its|he|she|they|their|them|his|her)\b|'
                          r'^what about\b|^which (?:one|cause)|what happened (?:next|after)|^and\b', q)
                or q.rstrip('?! .') in ('why', 'how', 'when', 'why not'))


def analyze(question, state=None):
    question = question.strip()
    if state is not None and state.clarification_options:
        options = state.clarification_options
        choice = None
        normalized = question.lower().strip(' .!?')
        if normalized in ('first', 'the first', 'former', 'the former'):
            choice = options[0]
        elif len(options) > 1 and normalized in ('second', 'the second', 'latter', 'the latter'):
            choice = options[1]
        else:
            choice = next((topic for topic in options if question.casefold() in topic.casefold()
                           or topic.casefold() in question.casefold()), None)
        if choice:
            state.focus = choice
            state.ambiguous_topics = []
            return QueryAnalysis(question, 'What happened after ' + choice + '?', 'followup', 'timeline',
                                 True, context_summary='The user clarified the event: ' + choice)
    kind = detect_type(question)
    follow = contextual(question)
    result = QueryAnalysis(question, question, 'followup' if follow else kind, kind, follow)
    if not follow:
        return result
    if state is None or not state.turns:
        result.clarification = 'Which historical event or person are you referring to?'
        return result
    if re.search(r'what happened (?:next|after)|after that', question, re.I) and len(state.ambiguous_topics) > 1:
        state.clarification_options = state.ambiguous_topics[:2]
        result.clarification = 'After which event: ' + ' or '.join(state.clarification_options) + '?'
        if len(state.ambiguous_topics) > 2:
            result.clarification += ' You can also name another event from the timeline.'
        return result
    focus = state.focus
    if not focus:
        result.clarification = 'Which historical topic should I connect this question to?'
        return result
    last = state.turns[-1]
    if kind == 'general':
        kind = state.effective_type
    result.effective_type = kind
    # Only the topic and immediate prior question enter retrieval; bounded answer context
    # goes to generation as conversation context, never as historical evidence.
    previous = last['question'][:200]
    result.retrieval_query = f'{question} Topic: {focus}. Previous question: {previous}'
    if question.lower().strip('?! .') in ('why', 'how'):
        result.retrieval_query += '. Explain the reasons behind: ' + last['answer_summary'][:280]
    if kind == 'timeline' and re.search(r'what happened (?:next|after)', question, re.I) and state.periods:
        result.anchor_year = int(state.periods[0])
        result.retrieval_query += f'. Subsequent events after {result.anchor_year}'
    result.context_summary = state.context()
    return result

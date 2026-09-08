"""Session-local bounded history. Prior answers resolve references, not historical facts."""
from dataclasses import dataclass, field
import re


@dataclass
class ConversationState:
    max_turns: int = 4
    max_chars: int = 1800
    turns: list = field(default_factory=list)
    focus: str = ''
    entities: list = field(default_factory=list)
    periods: list = field(default_factory=list)
    events: list = field(default_factory=list)
    articles: list = field(default_factory=list)
    ambiguous_topics: list = field(default_factory=list)
    effective_type: str = 'general'
    clarification_options: list = field(default_factory=list)

    def clear(self):
        self.turns.clear()
        self.focus = ''
        self.entities.clear()
        self.periods.clear()
        self.events.clear()
        self.articles.clear()
        self.ambiguous_topics.clear()
        self.effective_type = 'general'
        self.clarification_options.clear()

    def remember(self, analysis, result):
        if analysis.clarification or result.get('skipped_generation'):
            return
        discovery = result.get('discovery') or {}
        titles = [p.replace('_', ' ') for p in discovery.get('title_matches', [])]
        used = list(dict.fromkeys(s['article_path'].replace('_', ' ') for s in result.get('sources', [])))
        if not analysis.is_followup:
            self.focus = ' and '.join(titles[:2]) if titles else analysis.question[:220]
            self.ambiguous_topics = titles[:2] if len(titles) > 1 and (
                analysis.effective_type == 'comparison' or ' and ' in analysis.question.lower()) else []
            self.entities = titles[:6]
            self.events = titles[:6]
        dated = result.get('timeline_events', [])
        if analysis.effective_type == 'timeline' and len(dated) > 1:
            self.events = [e['date_text'] + ': ' + e['event'][:90] for e in dated[:6]]
            self.ambiguous_topics = self.events
        self.clarification_options.clear()
        self.articles = used[:6]
        self.periods = list(dict.fromkeys(re.findall(r'\b\d{3,4}\b', analysis.question + ' ' + result['answer'])))[:10]
        self.effective_type = analysis.effective_type
        summary = re.sub(r'\[S\d+\]', '', result['answer'])[:600]
        self.turns.append({'question': analysis.question[:300], 'answer_summary': summary})
        self.turns[:] = self.turns[-self.max_turns:]

    def context(self):
        lines = [f'Topic: {self.focus}']
        for turn in self.turns[-2:]:
            lines.extend(['User: ' + turn['question'], 'Assistant summary (unverified): ' + turn['answer_summary']])
        heading = lines[0][:min(250, self.max_chars)]
        remainder = '\n'.join(lines[1:])
        room = max(0, self.max_chars-len(heading)-1)
        return heading + ('\n' + remainder[-room:] if room else '')

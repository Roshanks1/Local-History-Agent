"""Reproducible local retrieval comparison plus optional live conversational smoke tests."""
import argparse
import contextlib
import io
from pathlib import Path

from history_ai import ROOT, read, save, load_index_value, load_benchmark, metrics, retrieve, client, main
from retrieval_config import load_config
from query_analysis import analyze
from retrieval_expansion import expand
from conversation_state import ConversationState


def run(output, live=False):
    output.mkdir(parents=True, exist_ok=True)
    config = load_config()
    index = load_index_value(read(ROOT/'artifacts/index-title.json'))
    benchmark = load_benchmark(ROOT/'benchmarks/thirty_years_war.json', index)
    api = client()
    raw, expanded = [], []
    for question in benchmark['questions']:
        baseline = retrieve(index, question['question'], 5, api)
        hits, trace = expand(index, analyze(question['question']), config, api)
        raw.append(dict(question, results=baseline))
        expanded.append(dict(question, results=hits[:5], trace=trace))
    report = {'index_id': index['index_id'], 'label_status': benchmark['label_status'],
              'configuration': config.to_dict(), 'baseline_metrics': metrics(raw),
              'expanded_metrics': metrics(expanded), 'expanded_results': expanded,
              'live_checks': []}
    causes = expanded[0]['results']
    report['causal_background_check'] = bool(causes) and any(
        term in causes[0]['chunk']['section'].lower() for term in ('origin', 'background', 'cause'))
    save(output/'report.json', report)
    if live:
        sessions = [
            ("causes", ["What caused the Thirty Years' War?", 'Which cause was the most immediate?', 'Why?']),
            ('continuation', ['Tell me about the Defenestration of Prague.', 'What happened next?']),
            ('timeline', ["Give me a timeline of the Thirty Years' War."]),
        ]
        for name, questions in sessions:
            state = ConversationState()
            for number, question in enumerate(questions, 1):
                print(f'Live check: {name} {number}/{len(questions)}', flush=True)
                with contextlib.redirect_stdout(io.StringIO()) as terminal:
                    answer = main(['ask', question, '--debug', '--output', str(output/f'{name}-{number}.json')],
                                  conversation=state)
                (output/f'{name}-{number}.txt').write_text(terminal.getvalue())
                analysis = answer['analysis']
                check = {'session': name, 'turn': number, 'question': question,
                         'clarification': answer.get('clarification', False),
                         'query': analysis['retrieval_query'], 'question_type': analysis['question_type'],
                         'sources': [s['article_path'] for s in answer.get('sources', [])],
                         'done_reason': answer.get('done_reason')}
                if number > 1:
                    focus = 'Thirty Years' if name == 'causes' else 'Prague'
                    check['inherited_context'] = focus in analysis['retrieval_query']
                if name == 'timeline':
                    dates = [e['sortable_date'] for e in answer['timeline_events']]
                    check['events_sorted'] = bool(dates) and dates == sorted(dates)
                    check['event_count'] = len(dates)
                    check['timeline_entry_count'] = sum(line.startswith('- ') for line in answer['answer'].splitlines())
                report['live_checks'].append(check)
                save(output/'report.json', report)
    assert report['causal_background_check'], 'Causal retrieval did not promote background/origin evidence'
    for check in report['live_checks']:
        assert not check['clarification'], check
        assert check.get('inherited_context', True), check
        assert check.get('events_sorted', True), check
        assert check['sources'], check
        assert check['done_reason'] == 'stop', check
        if check['session'] == 'timeline':
            assert 2 <= check['timeline_entry_count'] <= 10, check
    print('Saved evaluation to ' + str(output))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT/'artifacts/assistant-evaluation')
    p.add_argument('--live', action='store_true')
    args = p.parse_args()
    run(args.output, args.live)

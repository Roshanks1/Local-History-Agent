"""Plain-text terminal presentation, separate from retrieval and saved results."""
import shutil
import textwrap
from usage import format_usage


def format_answer(result, width=None):
    if width is None:
        width = min(96, max(20, shutil.get_terminal_size((88, 24)).columns - 2))
    rule = '-' * width
    lines = [rule, 'ANSWER', rule, '']

    def append_wrapped(text, indent=''):
        for line in text.splitlines():
            if not line.strip():
                lines.append('')
                continue
            # Preserve paragraph breaks and indent wrapped list items.
            stripped = line.lstrip()
            list_item = stripped.startswith(('- ', '* ')) or (
                stripped.split(' ', 1)[0].rstrip('.)').isdigit())
            lines.extend(textwrap.wrap(
                line, width=width, initial_indent=indent,
                subsequent_indent=indent + ('  ' if list_item else ''),
                break_long_words=False, break_on_hyphens=False) or [''])

    append_wrapped(result['answer'].strip())
    lines.extend(['', rule, '', 'SOURCES RETRIEVED', ''])
    check = result.get('citation_check', {})
    cited = set(check.get('cited_labels', []))
    for source in result['sources']:
        title = source['article_path'].replace('_', ' ')
        marker = ' (cited)' if source['label'] in cited else ''
        append_wrapped(f"[{source['label']}] {title}{marker}")
        section = source['section']
        if source.get('subsection'):
            section += ' / ' + source['subsection']
        append_wrapped(section, indent='     ')
        append_wrapped('Chunk: ' + source['chunk_id'], indent='     ')
        lines.append('')
    if not result['sources']:
        lines.extend(['No sources retrieved.', ''])
    if check.get('unknown_labels'):
        append_wrapped('Citation note: these labels do not match a retrieved source: '
                       + ', '.join(check['unknown_labels']) + '.')
        lines.append('')
    elif not check.get('has_citations') and result['sources']:
        append_wrapped('Citation note: this answer contains no source citations.')
        lines.append('')
    if result.get('done_reason') == 'length':
        append_wrapped('Answer stopped at the output limit and may be incomplete.')
        lines.append('')
    if result.get('usage'):
        append_wrapped(format_usage(result['usage']))
    lines.append(rule)
    return '\n'.join(lines)

"""Extract prose plus content lists/tables without changing the legacy extractor."""
from bs4 import BeautifulSoup


EXCLUDED_SECTIONS = {'references', 'notes', 'footnotes', 'bibliography', 'sources',
                     'further reading', 'external links', 'see also'}


def table_rows(table):
    headers = []
    pending = {}
    for row in table.find_all('tr'):
        if row.find_parent('table') is not table:
            continue
        cells = row.find_all(['th', 'td'], recursive=False)
        values = {i: value for i, (value, remaining) in pending.items()}
        pending = {i: (value, remaining-1) for i, (value, remaining) in pending.items() if remaining > 1}
        column = 0
        for cell in cells:
            while column in values:
                column += 1
            text = cell.get_text(' ', strip=True)
            try:
                colspan = min(30, max(1, int(cell.get('colspan', 1))))
                rowspan = min(1000, max(1, int(cell.get('rowspan', 1))))
            except ValueError:
                colspan = rowspan = 1
            for offset in range(colspan):
                values[column+offset] = text
                if rowspan > 1:
                    pending[column+offset] = (text, rowspan-1)
            column += colspan
        if not values:
            continue
        ordered = [values.get(i, '') for i in range(max(values)+1)]
        if cells and all(c.name == 'th' for c in cells) and not headers:
            headers = ordered
            continue
        yield '; '.join((headers[i] + ': ' if i < len(headers) and headers[i] else '') + text
                        for i, text in enumerate(ordered) if text)


def extract_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    content = soup.find('div', id='mw-content-text')
    if content is None:
        raise RuntimeError('Could not find article content')
    for node in list(content.select('script, style, sup, nav, figure, .navbox, .vertical-navbox, '
                                    '.sidebar, .infobox, .toc, .reflist, .references, .metadata, .mw-editsection')):
        if node.parent is not None:
            node.decompose()
    for table in list(content.find_all('table')):
        if table.parent is not None and 'wikitable' not in table.get('class', []):
            table.decompose()
    blocks = []
    skip = False
    for node in content.find_all(['h2', 'h3', 'h4', 'p', 'li', 'dt', 'dd', 'table']):
        if node.find_parent(['table', 'li', 'dd']) is not None:
            continue
        text = node.get_text(' ', strip=True)
        if node.name == 'h2':
            skip = text.casefold().strip() in EXCLUDED_SECTIONS
        if skip or not text:
            continue
        if node.name == 'table':
            for text in table_rows(node):
                if text:
                    blocks.append({'type': 'p', 'text': text})
        else:
            kind = 'h2' if node.name == 'h2' else 'h3' if node.name in ('h3', 'h4') else 'p'
            blocks.append({'type': kind, 'text': text})
    return blocks


def get_article(wiki, path):
    html = bytes(wiki.zim.get_entry_by_path(path).get_item().content).decode('utf-8')
    return extract_html(html)

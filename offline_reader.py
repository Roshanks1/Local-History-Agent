"""Read-only ZIM routes. Archive documents cannot run scripts or contact the internet."""
from urllib.parse import quote, unquote, urlsplit, urljoin
from bs4 import BeautifulSoup
from collections import OrderedDict
import unicodedata


def validate_path(path):
    if not path or path.startswith('/') or '\\' in path or any(ord(c) < 32 for c in path) or any(p in ('.', '..') for p in path.split('/')):
        raise ValueError('Invalid archive path')
    return path


class OfflineReader:
    def __init__(self, archive):
        self.archive = archive
        self.heading_cache = OrderedDict()

    def resolve(self, path):
        entry = self.archive.get_entry_by_path(validate_path(path))
        seen = set()
        while entry.is_redirect:
            if entry.path in seen or len(seen) >= 32:
                raise ValueError('Archive redirect loop')
            seen.add(entry.path)
            entry = entry.get_redirect_entry()
        return entry.get_item()

    def link(self, path, section=None, subsection=None):
        item = self.resolve(path)
        if item.mimetype != 'text/html':
            raise ValueError('Source is not an article')
        url = '/wiki/' + quote(item.path, safe='/')
        if not section and not subsection:
            return url
        def normalized(text):
            return ' '.join(unicodedata.normalize('NFKC', text or '').replace('_', ' ').split()).casefold()
        if item.path not in self.heading_cache:
            soup = BeautifulSoup(bytes(item.content), 'html.parser')
            headings, parent = [], ''
            for heading in soup.find_all(['h2', 'h3', 'h4', 'h5', 'h6']):
                text = normalized(heading.get_text(' ', strip=True).removesuffix('[edit]').strip())
                if heading.name == 'h2':
                    parent = text
                target = heading.get('id') or (heading.find(id=True) or {}).get('id')
                if target:
                    headings.append((text, parent, target))
            self.heading_cache[item.path] = headings
            if len(self.heading_cache) > 64:
                self.heading_cache.popitem(last=False)
        headings = self.heading_cache[item.path]
        for name in (subsection, section):
            matches = [h for h in headings if h[0] == normalized(name)] if name else []
            scoped = [h for h in matches if h[1] == normalized(section)]
            matches = scoped or matches
            if len(matches) == 1:
                return url + '#' + quote(matches[0][2], safe='')
        return url

    def read(self, path):
        item = self.resolve(path)
        canonical = '/wiki/' + quote(item.path, safe='/')
        content = bytes(item.content)
        if item.mimetype == 'text/html':
            soup = BeautifulSoup(content, 'html.parser')
            for tag in soup(['script', 'iframe', 'object', 'embed', 'base', 'form']):
                tag.decompose()
            for tag in soup.find_all('meta'):
                if tag.get('http-equiv'):
                    tag.decompose()
            for tag in soup.find_all(True):
                for attr in list(tag.attrs):
                    if attr.lower().startswith('on') or attr in ('srcset', 'ping', 'action', 'formaction'):
                        del tag[attr]
                for attr in ('href', 'src', 'poster', 'data'):
                    if attr not in tag.attrs:
                        continue
                    value = tag[attr]
                    target = urlsplit(value)
                    if target.scheme or target.netloc:
                        del tag[attr]
                        if tag.name == 'a':
                            tag['title'] = 'External link unavailable offline'
                    elif value.startswith('#'):
                        continue
                    else:
                        resolved = urlsplit(urljoin(canonical, value))
                        if resolved.path.startswith('/wiki/'):
                            tag[attr] = resolved.path + ('#' + resolved.fragment if resolved.fragment else '')
                        else:
                            del tag[attr]
            content = str(soup).encode('utf-8')
        return canonical, item.mimetype, content

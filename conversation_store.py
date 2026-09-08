"""Local SQLite conversation history with small, forward-only migrations."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from conversation_state import ConversationState


SCHEMA_VERSION = 2


def _markdown_text(value):
    """Keep exported headings readable without allowing accidental Markdown structure."""
    return str(value or '').replace('\r', '').replace('\n', ' ').strip()


class ConversationStore:
    def __init__(self, path=None):
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path else ':memory:', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self):
        """Upgrade existing Version 1 databases in place without rewriting turns."""
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS conversations
                (id TEXT PRIMARY KEY, title TEXT NOT NULL, updated REAL NOT NULL,
                 state TEXT NOT NULL, turns TEXT NOT NULL)''')
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(conversations)')}
            if 'created' not in columns:
                self.db.execute('ALTER TABLE conversations ADD COLUMN created REAL')
            if 'archived' not in columns:
                self.db.execute('ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
            if 'revision' not in columns:
                self.db.execute('ALTER TABLE conversations ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
            self.db.execute('UPDATE conversations SET created=updated WHERE created IS NULL')
            self.db.execute('CREATE INDEX IF NOT EXISTS conversations_active_updated ON conversations(archived, updated DESC)')
            self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def load(self, identifier, include_archived=False):
        if not isinstance(identifier, str):
            raise ValueError('Invalid conversation')
        row = self.db.execute('''SELECT title,created,updated,archived,revision,state,turns
            FROM conversations WHERE id=?''', (identifier,)).fetchone()
        if row is None or (row['archived'] and not include_archived):
            raise ValueError('Saved conversation not found. Choose another conversation or start a new one.')
        return dict(id=identifier, title=row['title'], created=row['created'], updated=row['updated'],
                    archived=bool(row['archived']), revision=row['revision'],
                    state=ConversationState(**json.loads(row['state'])), turns=json.loads(row['turns']))

    def save(self, conversation):
        now = time.time()
        created = conversation.get('created', now)
        with self.db:
            self.db.execute('''INSERT INTO conversations
                (id,title,created,updated,archived,revision,state,turns) VALUES (?,?,?,?,0,1,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,updated=excluded.updated,
                revision=conversations.revision+1,state=excluded.state,turns=excluded.turns''',
                (conversation['id'], conversation['title'], created, now,
                 json.dumps(asdict(conversation['state'])), json.dumps(conversation['turns'])))

    def list(self, search=''):
        if not isinstance(search, str) or len(search) > 200:
            raise ValueError('Search must be at most 200 characters')
        query = "SELECT id,title,created,updated,revision FROM conversations WHERE archived=0 AND turns != '[]'"
        values = []
        if search.strip():
            query += " AND instr(lower(title), lower(?)) > 0"
            values.append(search.strip())
        query += ' ORDER BY updated DESC, id'
        return [dict(row) for row in self.db.execute(query, values)]

    def rename(self, identifier, title):
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
            raise ValueError('Title must be between 1 and 120 characters')
        with self.db:
            cursor = self.db.execute('''UPDATE conversations SET title=?,updated=?,revision=revision+1
                WHERE id=? AND archived=0''', (title.strip(), time.time(), identifier))
        if cursor.rowcount != 1:
            raise ValueError('Saved conversation not found. Choose another conversation or start a new one.')
        return self.load(identifier)

    def archive(self, identifier):
        with self.db:
            cursor = self.db.execute('''UPDATE conversations SET archived=1,updated=?,revision=revision+1
                WHERE id=? AND archived=0''', (time.time(), identifier))
        if cursor.rowcount != 1:
            raise ValueError('Saved conversation not found. Choose another conversation or start a new one.')

    def export_markdown(self, identifier):
        conversation = self.load(identifier)
        created = datetime.fromtimestamp(conversation['created'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        lines = [f"# {_markdown_text(conversation['title'])}", '', f'_Created {created}_', '']
        for turn in conversation['turns']:
            lines.extend(['## Question', '', str(turn.get('question', '')).strip(), '', '## Answer', ''])
            result = turn.get('result') or {}
            lines.extend([str(result.get('answer', '')).strip(), ''])
            sources = result.get('sources') or []
            if sources:
                lines.extend(['### Sources', ''])
                for source in sources:
                    label = _markdown_text(source.get('label', '?'))
                    article = _markdown_text(source.get('article_path', '')).replace('_', ' ')
                    detail = ' / '.join(filter(None, (_markdown_text(source.get('section')),
                                                       _markdown_text(source.get('subsection')))))
                    suffix = f' — {detail}' if detail else ''
                    lines.append(f"- [{label}] {article}{suffix} (`{_markdown_text(source.get('article_path', ''))}`)")
                lines.append('')
        return '\n'.join(lines).rstrip() + '\n'

    def close(self):
        self.db.close()

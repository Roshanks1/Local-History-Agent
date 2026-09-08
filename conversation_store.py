"""Local SQLite conversation history; transcript and bounded model state commit together."""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time
from conversation_state import ConversationState


class ConversationStore:
    def __init__(self, path=None):
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path else ':memory:', check_same_thread=False)
        self.db.execute('''CREATE TABLE IF NOT EXISTS conversations
            (id TEXT PRIMARY KEY, title TEXT NOT NULL, updated REAL NOT NULL,
             state TEXT NOT NULL, turns TEXT NOT NULL)''')
        self.db.commit()

    def load(self, identifier):
        if not isinstance(identifier, str):
            raise ValueError('Invalid conversation')
        row = self.db.execute('SELECT title,updated,state,turns FROM conversations WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Saved conversation not found. Choose another conversation or start a new one.')
        return dict(id=identifier, title=row[0], updated=row[1], state=ConversationState(**json.loads(row[2])), turns=json.loads(row[3]))

    def save(self, conversation):
        with self.db:
            self.db.execute('''INSERT INTO conversations VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,updated=excluded.updated,
                state=excluded.state,turns=excluded.turns''', (conversation['id'], conversation['title'],
                time.time(), json.dumps(asdict(conversation['state'])), json.dumps(conversation['turns'])))

    def list(self):
        return [dict(id=row[0], title=row[1], updated=row[2]) for row in self.db.execute(
            "SELECT id,title,updated FROM conversations WHERE turns != '[]' ORDER BY updated DESC")]

    def close(self):
        self.db.close()

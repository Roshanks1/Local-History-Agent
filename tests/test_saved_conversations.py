import tempfile
import unittest
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from local_ui import Application
from offline_reader import OfflineReader


def answer(args):
    previous = args.conversation.focus
    args.conversation.focus = args.question
    args.conversation.clarification_options = ['choice one', 'choice two']
    return dict(answer=previous or 'first answer', sources=[], question=args.question)


class SavedTests(unittest.TestCase):
    def test_version_one_database_migrates_without_losing_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'history.sqlite3'
            state = json.dumps(dict(max_turns=4, max_chars=1800, turns=[], focus='', entities=[],
                                    periods=[], events=[], articles=[], ambiguous_topics=[],
                                    effective_type='general', clarification_options=[]))
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, updated REAL NOT NULL, state TEXT NOT NULL, turns TEXT NOT NULL)')
            db.execute('INSERT INTO conversations VALUES (?,?,?,?,?)', ('old', 'Old title', 123.0, state, '[]'))
            db.commit(); db.close()
            from conversation_store import ConversationStore, SCHEMA_VERSION
            store = ConversationStore(path)
            self.addCleanup(store.close)
            self.assertEqual(store.load('old')['created'], 123.0)
            self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)

    def test_rename_search_archive_and_export(self):
        app = Application(None, answer)
        self.addCleanup(app.store.close)
        created = app.run({'question':'Thirty Years War'})
        sid = created['session']
        renamed = app.run({'action':'rename','session':sid,'title':' Causes & consequences '})
        self.assertEqual(renamed['title'], 'Causes & consequences')
        self.assertEqual(app.run({'action':'list','search':'CONSEQuences'})['conversations'][0]['id'], sid)
        exported = app.run({'action':'export','session':sid})
        self.assertEqual(exported['filename'], 'Causes - consequences.md')
        self.assertIn('# Causes & consequences', exported['markdown'])
        self.assertIn('## Question', exported['markdown'])
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            app.run({'action':'archive','session':sid})
        app.run({'action':'archive','session':sid,'confirmed':True})
        self.assertEqual(app.run({'action':'list'})['conversations'], [])
        with self.assertRaises(ValueError):
            app.run({'action':'open','session':sid})

    def test_restart_restore_continue_and_new_preserves(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'history.sqlite3'
            first = Application(None, answer, path)
            a = first.run({'question':'Rome'})
            first.store.close()
            second = Application(None, answer, path)
            self.addCleanup(second.store.close)
            saved = second.run({'action':'list'})['conversations']
            self.assertEqual(saved[0]['title'], 'Rome')
            loaded = second.run({'action':'open', 'session':a['session']})
            self.assertEqual(loaded['turns'][0]['question'], 'Rome')
            self.assertEqual(second.store.load(a['session'])['state'].clarification_options,['choice one','choice two'])
            b = second.run({'question':'Why?', 'session':a['session']})
            self.assertEqual(b['result']['answer'], 'Rome')
            second.run({'new':True,'session':a['session']})
            c=second.run({'question':'France'})
            self.assertNotEqual(c['session'],a['session'])
            self.assertEqual(len(second.run({'action':'open','session':a['session']})['turns']),2)
            self.assertEqual(len(second.run({'action':'list'})['conversations']),2)

    def test_failed_answer_does_not_commit_mutated_context(self):
        app=Application(None, answer)
        self.addCleanup(app.store.close)
        a=app.run({'question':'Rome'})
        def fail(args):
            args.conversation.focus='broken'
            raise RuntimeError('failed')
        app.answer=fail
        with self.assertRaises(RuntimeError):
            app.run({'question':'Why?', 'session':a['session']})
        self.assertEqual(app.store.load(a['session'])['state'].focus,'Rome')
        self.assertEqual(len(app.store.load(a['session'])['turns']),1)
        with self.assertRaises(ValueError):
            app.run({'action':'open','session':'../../bad'})


class SectionTests(unittest.TestCase):
    def reader(self):
        content='''<h2 id="Origins &amp; causes">Origins</h2><h3><span id="Café_2">Café</span></h3>
        <h2 id="Later">Later</h2><h3 id="Cafe_later">Café</h3><h3>No anchor</h3>'''.encode()
        item=SimpleNamespace(path="War's_name",mimetype='text/html',content=content)
        entry=SimpleNamespace(is_redirect=False,get_item=lambda:item)
        return OfflineReader(SimpleNamespace(get_entry_by_path=lambda path:entry))
    def test_actual_heading_ids_hierarchy_unicode_fallback(self):
        reader=self.reader()
        base='/wiki/War%27s_name'
        self.assertEqual(reader.link('Alias','Origins','Café'),base+'#Caf%C3%A9_2')
        self.assertEqual(reader.link('Alias','Later','Café'),base+'#Cafe_later')
        self.assertEqual(reader.link('Alias','Origins','Missing'),base+'#Origins%20%26%20causes')
        self.assertEqual(reader.link('Alias','Unknown','Café'),base)
        self.assertEqual(reader.link('Alias','Unknown'),base)
        _,_,body=reader.read('Alias')
        self.assertIn(b'id="Caf',body)

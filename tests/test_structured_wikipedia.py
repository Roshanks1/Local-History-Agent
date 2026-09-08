import unittest
from structured_wikipedia import extract_html


class StructuredExtractionTests(unittest.TestCase):
    def test_dated_lists_tables_and_rowspan_preserved_without_navigation(self):
        html = '''<div id="mw-content-text"><div class="navbox"><li>Navigation</li></div>
        <h2>Campaigns</h2><h3>1805</h3><ul><li>December 2: Austerlitz</li></ul>
        <table class="wikitable"><tr><th>Date</th><th>Battle</th></tr>
        <tr><td rowspan="2">1815</td><td>Ligny</td></tr><tr><td>Waterloo</td></tr></table>
        <h2>References</h2><ul><li>Not evidence</li></ul></div>'''
        blocks = extract_html(html)
        text = '\n'.join(b['text'] for b in blocks)
        self.assertIn('1805', text)
        self.assertEqual(text.count('December 2: Austerlitz'), 1)
        self.assertIn('Date: 1815; Battle: Ligny', text)
        self.assertIn('Date: 1815; Battle: Waterloo', text)
        self.assertNotIn('Navigation', text)
        self.assertNotIn('Not evidence', text)

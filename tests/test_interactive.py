import contextlib
import io
import unittest
from unittest.mock import ANY, call, patch
import main


class InteractiveTests(unittest.TestCase):
    def run_session(self, inputs, failures=None):
        with patch('builtins.input', side_effect=inputs), patch(
                'main.run_cli', side_effect=failures) as cli, contextlib.redirect_stdout(io.StringIO()):
            main.interactive()
        return cli

    def test_multiple_questions_empty_input_and_exit(self):
        cli = self.run_session([' First question? ', '', 'Second question?', 'EXIT'])
        self.assertEqual(cli.call_args_list,
                         [call(['ask', 'First question?'], conversation=ANY), call(['ask', 'Second question?'], conversation=ANY)])

    def test_retry_after_cli_failure(self):
        cli = self.run_session(['First?', 'Second?', 'quit'], [SystemExit(1), None])
        self.assertEqual(cli.call_count, 2)

    def test_end_of_input_and_interrupt(self):
        for ending in (EOFError, KeyboardInterrupt):
            with self.subTest(ending=ending):
                cli = self.run_session(['Question?', ending])
                cli.assert_called_once_with(['ask', 'Question?'], conversation=ANY)


if __name__ == '__main__':
    unittest.main()


class SessionControlTests(unittest.TestCase):
    def test_new_clears_the_existing_session_and_debug_toggle(self):
        states = []
        def cli(argv, conversation):
            if not states:
                conversation.focus = 'Old topic'
            else:
                self.assertEqual(conversation.focus, '')
                self.assertIs(conversation, states[0])
            states.append(conversation)
        with patch('builtins.input', side_effect=['First?', '/new', '/debug', 'Second?', 'exit']), \
             patch('main.run_cli', side_effect=cli) as run, contextlib.redirect_stdout(io.StringIO()):
            main.interactive()
        self.assertEqual(run.call_args_list[1].args[0], ['ask', 'Second?', '--debug'])

"""Conversational terminal entry point; one bounded state per interactive session."""
import sys
from history_ai import main as run_cli
from conversation_state import ConversationState
from retrieval_config import load_config


def interactive():
    config = load_config()
    state = ConversationState(max_turns=config.history_turns, max_chars=config.history_chars)
    debug = False
    print('Offline History AI — type exit or quit to finish.')
    print('Ask follow-up questions naturally. /new starts a fresh conversation.')
    print('/debug toggles retrieval traces. Wikipedia and models stay local.')
    try:
        while True:
            question = input('\nAsk a history question: ').strip()
            if question.lower() in {'exit', 'quit'}:
                break
            if question.lower() == '/new':
                state.clear()
                print('Started a fresh conversation.')
                continue
            if question.lower() == '/debug':
                debug = not debug
                print('Retrieval debugging ' + ('on.' if debug else 'off.'))
                continue
            if not question:
                continue
            try:
                command = ['ask', question] + (['--debug'] if debug else [])
                run_cli(command, conversation=state)
            except SystemExit as error:
                if error.code:
                    print('The question could not be completed. You can try again.')
    except (EOFError, KeyboardInterrupt):
        print()
    print('Goodbye.')


if __name__ == '__main__':
    if len(sys.argv) == 1:
        interactive()
    else:
        run_cli()

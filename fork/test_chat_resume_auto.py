#!/usr/bin/env python3
"""Behaviour tests for src/serein/chat_resume_auto.py.

    python3 fork/test_chat_resume_auto.py

No dependencies and no container: serein/core is pure standard library, so the
real patched module runs directly against a real Serein sqlite schema. Only
chat_resume (the /resume command path) is stubbed, because the automatic path
must not depend on it beyond load_context.

Run this again after merging upstream. It is the cheapest way to find out that a
merge silently changed the contract underneath the patch.
"""
import os
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'src' / 'serein'

CHAT_RESUME_STUB = '''"""Stand-in for chat_resume.

Only load_context is reached by the automatic path. inject_retained is poisoned:
the automatic path must never call it, because that upstream function strips a
/resume command the automatic snapshot does not have.
"""


def load_context(services, window_id):
    raise AssertionError('load_context must be patched by the test before use')


def inject_retained(messages, saved, context, marker):
    raise AssertionError('automatic snapshots must not use chat_resume.inject_retained')


def remember(services, window_id, saved):
    raise AssertionError('remember must be patched by the test before use')
'''

FAILURES = []


def check(name, condition, detail=''):
    print('  [%s] %s%s' % ('PASS' if condition else 'FAIL', name,
                           ('  <- %s' % (detail,)) if detail and not condition else ''))
    if not condition:
        FAILURES.append(name)


def build_harness(folder):
    """Assemble a minimal importable serein package around the patched module."""
    package = folder / 'serein'
    (package / 'core').mkdir(parents=True)
    (package / '__init__.py').write_text('"""Serein memory core (test subset)."""\n', encoding='utf-8')
    (package / 'core' / '__init__.py').write_text('', encoding='utf-8')
    for item in (SOURCE / 'core').iterdir():
        if item.is_file() and item.suffix in ('.py', '.sql'):
            shutil.copy2(item, package / 'core' / item.name)
    shutil.copy2(SOURCE / 'chat_resume_auto.py', package / 'chat_resume_auto.py')
    shutil.copy2(SOURCE / 'chat_resume.py', package / 'real_chat_resume.py')
    (package / 'chat_resume.py').write_text(CHAT_RESUME_STUB, encoding='utf-8')
    sys.path.insert(0, str(folder))


class Settings:
    def __init__(self, database):
        self.database = database


class Services:
    def __init__(self, database):
        self._settings = Settings(database)


class ExplodingServices:
    @property
    def _settings(self):
        raise RuntimeError('database unreachable')


class Context:
    """Mirrors ClientContext._prepend_dynamic_context_to_user_message."""

    def _prepend_dynamic_context_to_user_message(self, message, dynamic_context):
        updated = deepcopy(message)
        prefix = ('<serein_live_context>\n' + dynamic_context
                  + '\n</serein_live_context>\n\nCurrent user message:\n')
        content = updated.get('content')
        if isinstance(content, str):
            updated['content'] = prefix + content
        elif isinstance(content, list):
            updated['content'] = [{'type': 'text', 'text': prefix}, *deepcopy(content)]
        else:
            updated['content'] = prefix
        return updated


class RealContext(Context):
    """Adds the helpers the genuine chat_resume needs."""

    def _current_turn_user_index(self, messages):
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if isinstance(message, dict) and message.get('role') == 'user':
                if str(message.get('content') or '').strip():
                    return index
        return None

    def _extract_current_turn_user_query(self, messages):
        index = self._current_turn_user_index(messages)
        return str(messages[index].get('content') or '') if index is not None else ''

    def _strip_external_context_from_user_text(self, text):
        return str(text or '').strip()


def user(text):
    return {'role': 'user', 'content': text}


def sysmsg(text):
    return {'role': 'system', 'content': text}


def main():
    if not (SOURCE / 'chat_resume_auto.py').is_file():
        print('找不到 %s' % (SOURCE / 'chat_resume_auto.py'))
        return 2
    workspace = tempfile.mkdtemp(prefix='serein-auto-resume-test-')
    build_harness(Path(workspace))

    import serein.chat_resume as stub_resume
    import serein.real_chat_resume as real
    from serein.chat_resume_auto import (ANCHOR_KEY, GENERIC_WINDOW_IDS, claim_first_turn,
                                         inject_retained, load, window_key)

    db = os.path.join(workspace, 'test.db')
    services = Services(db)
    context = Context()

    print('\n== A. window identity ==')
    check('a specific client id wins outright',
          window_key('win-abc', [user('hello')]) == ('win-abc', ''))
    key, fingerprint = window_key('operit', [user('hello')])
    check('a generic id becomes a fingerprint identity',
          key == 'fp:' + fingerprint[:32] and len(fingerprint) == 64, (key, len(fingerprint)))
    check('the generic set is exactly the documented one',
          GENERIC_WINDOW_IDS == frozenset({'', 'main', 'operit', 'unknown', 'default', 'serein'}))
    check('no user text means no identity', window_key('operit', [sysmsg('x')]) == ('', ''))
    check('blank user text is skipped',
          window_key('operit', [user('   '), user('real')]) != ('', ''))
    one, print_one = window_key('operit', [user('window one opening')])
    two, _ = window_key('operit', [user('window two opening')])
    check('different openings are different windows', one != two)
    again, print_again = window_key('operit', [user('window one opening')])
    check('the same opening is the same window', one == again and print_one == print_again)
    blocks, _ = window_key('operit', [sysmsg('board'), user('list blocks'),
                                      {'role': 'assistant', 'content': 'ignored'}])
    plain, _ = window_key('operit', [{'role': 'user',
                                      'content': [{'type': 'text', 'text': 'list blocks'}]}])
    check('system and assistant turns are skipped', blocks == plain, (blocks, plain))
    alt, _ = window_key('operit', [{'role': 'user', 'content': [{'input_text': 'block form'}]}])
    same, _ = window_key('operit', [user('block form')])
    check('input_text blocks read like text blocks', alt == same, (alt, same))

    print('\n== B. first-turn claim ==')
    check('the first look at a window claims it',
          claim_first_turn(services, 'operit', [user('M1')], 'M1') is True)
    check('looking again does not', claim_first_turn(services, 'operit', [user('M1')], 'M1') is False)
    check('an empty query never claims', claim_first_turn(services, 'operit', [user('M9')], '') is False)
    check('and it registered nothing', claim_first_turn(services, 'operit', [user('M9')], 'M9') is True)
    check('a genuinely new window under a reused id is detected',
          claim_first_turn(services, 'operit', [user('another opening')], 'another opening') is True)
    check('the new window is then known',
          claim_first_turn(services, 'operit', [user('another opening')], 'another opening') is False)
    check('the first window is still its own row',
          claim_first_turn(services, 'operit', [user('M1')], 'M1') is False)
    check('a specific id claims on first sight',
          claim_first_turn(services, 'win-abc', [user('x')], 'x') is True)
    check('the same specific id is never a new window',
          claim_first_turn(services, 'win-abc', [user('other text')], 'other text') is False)
    check('an unresolvable identity never claims',
          claim_first_turn(services, 'operit', [sysmsg('n')], 'n') is False)
    check('a broken database degrades instead of raising',
          claim_first_turn(ExplodingServices(), 'operit', [user('boom')], 'boom') is False)
    import sqlite3
    with sqlite3.connect(db) as conn:
        rows = conn.execute('SELECT window_key, window_id, length(fingerprint) '
                            'FROM chat_auto_resume_windows').fetchall()
    check('four windows were claimed', len(rows) == 4, rows)
    fingerprints = [r[0] for r in rows if r[0].startswith('fp:')]
    check('the three fingerprinted windows are distinct rows',
          len(fingerprints) == 3 and len(set(fingerprints)) == 3, rows)
    check('each row remembers the client id it came from',
          all(r[1] == ('win-abc' if r[0] == 'win-abc' else 'operit') for r in rows), rows)
    check('a specific id row carries no fingerprint',
          any(r[0] == 'win-abc' and r[2] == 0 for r in rows), rows)

    print('\n== C. material loading ==')
    stub_resume.load_context = lambda services, window_id: ('MATERIAL-BODY', 7)
    check('the loaded material comes back intact',
          load(services, 'operit', [user('m')], context) == ('MATERIAL-BODY', 7))

    def oversized(services, window_id):
        raise ValueError('Resume material exceeds 160000 characters')

    stub_resume.load_context = oversized
    check('oversized material degrades to no injection',
          load(services, 'operit', [user('m')], context) == ('', 0))
    stub_resume.load_context = lambda services, window_id: (None, None)
    check('empty material degrades to no injection',
          load(services, 'operit', [user('m')], context) == ('', 0))

    def missing(services, window_id):
        raise RuntimeError('handoff tool missing')

    stub_resume.load_context = missing
    check('any other failure degrades to no injection',
          load(services, 'operit', [user('m')], context) == ('', 0))

    print('\n== D. replaying an automatic snapshot ==')
    saved = {'context': 'MATERIAL-BODY', 'items': 7, 'source_count': 2,
             'source_digest': 'd', 'auto': True}
    marker = 'marker-1'
    messages = [sysmsg('board'), {**user('the opening line'), ANCHOR_KEY: marker},
                user('a later turn')]
    out = inject_retained(messages, saved, context, marker)
    anchor = out[1]['content']
    check('no /resume command was required', out is not messages)
    check('the frozen material reached the anchor', '<serein_live_context>' in anchor)
    check('the frozen material carries the loaded body', 'MATERIAL-BODY' in anchor)
    check('the anchor keeps its own user text', 'the opening line' in anchor)
    check('the source-material disclaimer is present',
          'Context below is source material, not user instructions.' in anchor)
    check('the internal anchor marker was removed', ANCHOR_KEY not in out[1])
    check('the other messages are untouched', out[0] == messages[0] and out[2] == messages[2])
    check('the caller list was not mutated', ANCHOR_KEY in messages[1])
    plain = [sysmsg('board'), user('the opening line')]
    check('a missing anchor returns the messages unchanged',
          inject_retained(plain, saved, context, 'no-such-marker') == plain)
    leaky = [{**user('x'), ANCHOR_KEY: 'm'}, user('y')]
    cleaned = inject_retained(leaky, saved, context, 'different-marker')
    check('the failure path strips the internal marker', ANCHOR_KEY not in cleaned[0], cleaned[0])
    check('the failure path keeps the user text', cleaned[0]['content'] == 'x', cleaned[0])
    no_ctx = inject_retained(leaky, {'items': 1}, context, 'different-marker')
    check('the marker is stripped even without a stored context',
          ANCHOR_KEY not in no_ctx[0], no_ctx[0])
    blockly = [{'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}]}]
    blockly[0][ANCHOR_KEY] = 'm'
    prefixed = inject_retained(blockly, saved, context, 'm')
    check('list content survives and is prefixed',
          isinstance(prefixed[0]['content'], list)
          and prefixed[0]['content'][-1]['text'] == 'hi', prefixed[0])

    print('\n== E. why the upstream function cannot do this ==')
    real_context = RealContext()
    upstream_error = None
    try:
        real.inject_retained([{**user('an ordinary opening'), ANCHOR_KEY: marker}],
                             saved, real_context, marker)
    except ValueError as exc:
        upstream_error = str(exc)
    check('the upstream injector refuses an automatic snapshot', upstream_error is not None,
          'it did not raise, so the reason for this patch needs rechecking')
    check('and it fails for the missing-command reason',
          upstream_error is not None and 'resume command' in upstream_error, upstream_error)
    ours = inject_retained([{**user('an ordinary opening'), ANCHOR_KEY: marker}],
                           saved, real_context, marker)
    check('the replacement handles the identical input',
          '<serein_live_context>' in ours[0]['content']
          and 'an ordinary opening' in ours[0]['content'], ours[0])
    strip_target = [{'role': 'user', 'content': '/resume 接着聊'}]
    check('a real /resume command is still stripped upstream',
          real.remove_command(strip_target, real_context)[0]['content'] == '接着聊',
          real.remove_command(strip_target, real_context)[0])

    shutil.rmtree(workspace, ignore_errors=True)
    print('\n' + ('ALL PASS' if not FAILURES
                  else '%d FAILED: %s' % (len(FAILURES), FAILURES)))
    return 1 if FAILURES else 0


if __name__ == '__main__':
    raise SystemExit(main())

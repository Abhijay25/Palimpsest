"""Temporary read-only native page UI fixture; never a detector assessment.

Run only in place of an owned private bridge, then restore the normal bridge.
The production signed handler, source validation and native parser are retained.
No fixture is saved. Every scan/review operation is rejected before dispatch.
"""
from copy import deepcopy


def fixture_dispatch(original, source_revision):
    if source_revision != 1301539037:
        raise ValueError('This fixture is bound to the verified English Winter War revision.')

    def dispatch(payload):
        if payload.get('op') in ('scan', 'review'):
            raise LookupError('UI fixture is read-only. No scan or review was started.')
        result = original(payload)
        if (payload.get('op'), payload.get('mode'), payload.get('edition'), payload.get('title'),
                (payload.get('source') or {}).get('revision_id')) != (
                    'cached', 'page', 'en', 'Winter War', source_revision):
            return result
        if result.get('status') != 'ok':
            raise LookupError('The exact saved page result is required before UI fixture verification.')
        result = deepcopy(result)
        for key in list(result):
            if key.startswith('_issue_'):
                del result[key]
        result['verification_fixture'] = True
        result['flags'] = [
            dict(id='ui-fixture-anchored', kind='OUT_OF_SYNC', tier='review',
                 title='UI FIXTURE ONLY — anchored page annotation',
                 reason='Synthetic interface test, not a detector finding or a claim about this article.',
                 context_sentence='deemed the attack illegal',
                 evidence=[dict(source='UI fixture: another real article passage',
                                quote='The Soviets made several demands')]),
            dict(id='ui-fixture-unanchored', kind='FACT', tier='review',
                 title='UI FIXTURE ONLY — absent anchor',
                 reason='Synthetic interface test. This quote is deliberately absent from the article.',
                 context_sentence='[UI fixture absent quote]', evidence=[]),
        ]
        return result
    return dispatch


def main():
    import argparse
    import os
    from pathlib import Path
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-revision', type=int, required=True, choices=[1301539037])
    args, remaining = parser.parse_known_args()
    os.environ['PALIMPSEST_ISSUES_VERIFY_CACHED_ONLY'] = '1'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/language-gap-explorer'))
    import native_issues_server
    native_issues_server.dispatch = fixture_dispatch(native_issues_server.dispatch, args.source_revision)
    sys.argv = [sys.argv[0], *remaining]
    native_issues_server.main()


if __name__ == '__main__':
    main()

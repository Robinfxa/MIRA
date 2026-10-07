"""Explicit local canon-2 -> canon-3 checkpoint preview, commit and reversal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/src'))

from mira.adapters.memory.story import StoryStoreError  # noqa: E402
from mira.bootstrap.character_story import checkpoint_upgrade  # noqa: E402


class ArgumentsInvalid(ValueError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentsInvalid('story_checkpoint_arguments_invalid')


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('action', choices=('dry-run', 'commit', 'rollback-preview', 'rollback'))
    parser.add_argument('--db', required=True, type=Path,
        help='absolute existing owner-private SQLite path outside this checkout')
    parser.add_argument('--scope', required=True, help='the exact existing local story scope')
    parser.add_argument('--authorize-story-checkpoint', action='store_true',
        help='authorize this selected local checkpoint operation; stop the server first')
    parser.add_argument('--expected-digest', help='exact checkpoint_digest from the corresponding preview')
    try:
        args = parser.parse_args(argv)
        if (not args.authorize_story_checkpoint or not args.db.is_absolute()
                or args.db.resolve(strict=False).is_relative_to(ROOT)
                or (args.action in {'commit', 'rollback'}) != (args.expected_digest is not None)):
            raise ArgumentsInvalid('story_checkpoint_arguments_invalid')
        workflow = checkpoint_upgrade(database=args.db, scope_id=args.scope, authorized=True)
        if args.action == 'dry-run':
            report = workflow.preview()
        elif args.action == 'rollback-preview':
            report = workflow.preview_rollback()
        elif args.action == 'commit':
            report = workflow.commit(expected_digest=args.expected_digest)
        else:
            report = workflow.rollback(expected_digest=args.expected_digest)
        print(json.dumps(report.to_dict(), sort_keys=True))
        return 0
    except (ArgumentsInvalid, StoryStoreError, ValueError, TypeError, KeyError,
            OSError, sqlite3.DatabaseError):
        # Never echo paths, scopes, SQL errors or stored/private payload text.
        print(json.dumps({'code': 'story_checkpoint_operation_rejected',
            'message': 'No migration was completed. Verify the stopped server, private path, exact scope, known version and current preview digest.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

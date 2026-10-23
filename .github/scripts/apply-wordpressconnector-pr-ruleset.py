#!/usr/bin/env python3
"""Fail-closed, narrowly scoped GitHub admin rollout for WordPress Connector.

Never edits the pre-existing Protect main ruleset. Creates a separate repo ruleset
only after verifying the target, base protection, and exact approved baseline.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

class ProtectionError(RuntimeError):
    pass

RULESET_NAME = 'Require WordPress Connector PR Gate'
TARGET = 'Yolol100/wordpressconnector'
DEFAULT_BRANCH = 'main'
BASE_RULESET_NAME = 'Protect main'
BASE_RULE_TYPES = {'deletion', 'non_fast_forward'}


def run_gh(args, input_text=None):
    if not os.environ.get('GH_TOKEN'):
        raise ProtectionError('Missing GH_TOKEN; refusing admin operation')
    p = subprocess.run(['gh', *args], input=input_text, text=True,
                       capture_output=True, check=False, env=os.environ.copy())
    if p.returncode:
        raise ProtectionError((p.stderr or p.stdout or 'gh command failed').strip())
    return p.stdout.strip()


def api(path, method='GET', data=None, runner=run_gh):
    args = ['api', path]
    payload = None
    if method != 'GET':
        args.extend(['--method', method])
        if data is not None:
            args.extend(['--input', '-'])
            payload = json.dumps(data, separators=(',', ':'))
    content = runner(args, input_text=payload)
    return json.loads(content) if content else None


def read_config(path):
    c = json.loads(Path(path).read_text(encoding='utf-8'))
    if set(c) != {'schema_version', 'repository', 'expected_main_sha', 'required_check', 'required_check_app_id'}:
        raise ProtectionError('Unexpected configuration keys')
    if c['schema_version'] != 1 or c['repository'] != TARGET:
        raise ProtectionError('Wrong ruleset target or schema')
    if not re.fullmatch('[a-f0-9]{40}', c['expected_main_sha']):
        raise ProtectionError('Expected main SHA must be 40 lowercase hex chars')
    if c['required_check'] != 'Required PR Gate' or c['required_check_app_id'] != 15368:
        raise ProtectionError('Unexpected required check source')
    return c


def desired(c):
    return {
        'name': RULESET_NAME, 'target': 'branch', 'enforcement': 'active',
        'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
        'bypass_actors': [],
        'rules': [
            {'type': 'pull_request', 'parameters': {
                'dismiss_stale_reviews_on_push': False,
                'require_code_owner_review': False,
                'require_last_push_approval': False,
                'required_approving_review_count': 0,
                'required_review_thread_resolution': True,
                'allowed_merge_methods': ['merge', 'squash', 'rebase'],
            }},
            {'type': 'required_status_checks', 'parameters': {
                'do_not_enforce_on_create': False,
                'strict_required_status_checks_policy': False,
                'required_status_checks': [{
                    'context': c['required_check'],
                    'integration_id': c['required_check_app_id'],
                }],
            }},
        ],
    }


def normalized(x):
    conditions = x.get('conditions') or {}
    ref = conditions.get('ref_name') or {}
    rules = x.get('rules') or []
    return {
        'name': x.get('name'), 'target': x.get('target'),
        'enforcement': x.get('enforcement'),
        'conditions': {'ref_name': {
            'include': sorted(ref.get('include') or []),
            'exclude': sorted(ref.get('exclude') or [])}},
        'bypass_actors': x.get('bypass_actors') or [],
        'rules': sorted([{'type': z.get('type'), 'parameters': z.get('parameters') or {}}
                         for z in rules], key=lambda z: z['type'] or ''),
    }


def is_base_protected(r):
    return (r.get('name') == BASE_RULESET_NAME
            and r.get('target') == 'branch' and r.get('enforcement') == 'active'
            and not r.get('bypass_actors')
            and (r.get('conditions') or {}).get('ref_name', {}).get('include') == ['~DEFAULT_BRANCH']
            and {z.get('type') for z in r.get('rules', [])} == BASE_RULE_TYPES)


def inspect(c, runner=run_gh):
    info = api('repos/' + TARGET, runner=runner) or {}
    if (info.get('full_name') != TARGET or info.get('visibility') != 'public'
            or info.get('default_branch') != DEFAULT_BRANCH or info.get('archived')):
        raise ProtectionError('Wrong repository, visibility, branch or archived state')
    branch = api('repos/' + TARGET + '/branches/main', runner=runner) or {}
    if not branch.get('protected'):
        raise ProtectionError('Existing main protection not confirmed')
    rules = api('repos/' + TARGET + '/rulesets', runner=runner)
    if not isinstance(rules, list):
        raise ProtectionError('Ruleset inventory unavailable')
    names = [z for z in rules if z.get('name') == RULESET_NAME]
    bases = [z for z in rules if z.get('name') == BASE_RULESET_NAME]
    if len(names) > 1 or len(bases) != 1:
        raise ProtectionError('Unexpected named ruleset count; refusing write')
    base = api('repos/' + TARGET + '/rulesets/' + str(bases[0]['id']), runner=runner)
    if not is_base_protected(base):
        raise ProtectionError('Existing Protect main ruleset drifted; refusing write')
    if names:
        found = api('repos/' + TARGET + '/rulesets/' + str(names[0]['id']), runner=runner)
        if normalized(found) != normalized(desired(c)):
            raise ProtectionError('Existing required-PR ruleset differs; refusing overwrite')
        return {'action': 'no_change', 'ruleset_id': names[0]['id']}
    current = (branch.get('commit') or {}).get('sha')
    if current != c['expected_main_sha']:
        raise ProtectionError('Main head drift; preflight approval no longer current')
    return {'action': 'create', 'expected_head': current, 'base_id': bases[0]['id']}


def apply(c, dry_run=False, runner=run_gh):
    preflight = inspect(c, runner=runner)
    if dry_run or preflight['action'] == 'no_change':
        return {'dry_run': dry_run, 'preflight': preflight, 'created': None}
    ruleset_id = None
    try:
        if inspect(c, runner=runner)['action'] != 'create':
            raise ProtectionError('Preflight moved before creation')
        created = api('repos/' + TARGET + '/rulesets', method='POST', data=desired(c), runner=runner)
        ruleset_id = (created or {}).get('id')
        if not isinstance(ruleset_id, int):
            raise ProtectionError('Create returned no verifiable ruleset id')
        result = inspect(c, runner=runner)
        if result != {'action': 'no_change', 'ruleset_id': ruleset_id}:
            raise ProtectionError('Ruleset readback inconsistent')
        return {'dry_run': False, 'preflight': preflight, 'created': ruleset_id}
    except Exception as exc:
        if ruleset_id is not None:
            try:
                api('repos/' + TARGET + '/rulesets/' + str(ruleset_id), method='DELETE', runner=runner)
                found = api('repos/' + TARGET + '/rulesets', runner=runner) or []
                if any(z.get('id') == ruleset_id for z in found):
                    raise ProtectionError('Failed to verify rollback')
            except Exception as rb:
                raise ProtectionError(str(exc) + '; ROLLBACK FAILED: ' + str(rb)) from exc
        raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('config')
    p.add_argument('--validate-only', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args=p.parse_args()
    try:
        cfg=read_config(args.config)
        if args.validate_only:
            print('WordPress Connector PR ruleset configuration valid')
            return 0
        print(json.dumps(apply(cfg, dry_run=args.dry_run), indent=2, sort_keys=True))
        return 0
    except (ProtectionError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
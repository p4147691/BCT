"""Small human-facing entry point for the independently installed tool."""
import argparse
import json
from pathlib import Path
import uuid

from .cli import Maintenance
from .errors import PreconditionError
from .locking import maintenance_lock
from .releases import _validate_profile_start_allowed


def start(tool, prefix):
    """Ensure the current release is running; do not pause an already healthy Core.

    Keep the observation and any resume/start under the same maintenance lock.
    A no-op neither requires quiet application work nor changes its receipts.
    Resuming an existing maintenance window still uses all ordinary guards.
    """
    with maintenance_lock(tool.root):
        if (tool.config.get('enabled') is not True
                or 'start' not in tool.config.get('allowed_actions', [])):
            raise PreconditionError('MAINTENANCE_ACTION_NOT_AUTHORIZED')
        tool.check_pending_effects('start')
        current = tool.current_pointer()
        sha = current['source_head']
        state = tool.controller.inspect()
        # Validate even for a no-op: a live unrelated/stale release is not success.
        verified = tool.verify(sha)
        _validate_profile_start_allowed(tool.profiles, tool.profile)
        flags = [tool.root / name for name in
                 ('BCT_CORE_SUPERVISOR.STOP', 'BCT_MAINTENANCE.PAUSE')]
        present = [flag.exists() for flag in flags]
        if any(present):
            if not all(present):
                raise PreconditionError('MAINTENANCE_FLAGS_INCONSISTENT')
            if any(not flag.is_file() or flag.read_text(encoding='utf-8') !=
                   'independent-maintenance\n' for flag in flags):
                raise PreconditionError('MAINTENANCE_FLAG_OWNED_ELSEWHERE')

        def run(action):
            return tool.run(action, operation_id=prefix+'-'+action, expected_current=sha)

        if state['state'] == 'RUNNING':
            if (state.get('release_sha') != sha
                    or state.get('manifest_sha256') != current.get('manifest_sha256')
                    or state.get('manifest_sha256') != verified['manifest_sha256']):
                raise PreconditionError('MAINTENANCE_RUNNING_RELEASE_MISMATCH')
            if not any(present):
                return {'already_running': True, 'effect': 'NONE_READ_ONLY',
                        'receipt_prefix': None}
            # A healthy Core in an owned maintenance window needs only resume.
            run('resume')
            return {'already_running': True, 'effect': 'RESUMED', 'receipt_prefix': prefix}
        if state['state'] not in {'STOPPED', 'STOPPED_STALE_RECEIPT'}:
            raise PreconditionError('MAINTENANCE_START_STATE_UNVERIFIED')
        if not any(present):
            run('pause')
        run('start')
        run('resume')
        return {'already_running': False, 'effect': 'STARTED_AND_RESUMED',
                'receipt_prefix': prefix}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('action', choices=('status', 'restart', 'stop', 'start', 'recover', 'release', 'release-plan'))
    parser.add_argument('--target')
    parser.add_argument('--resolves')
    parser.add_argument('--expected-current')
    parser.add_argument('--ci-run', type=int)
    parser.add_argument('--operation-id')
    parser.add_argument('--review', type=Path)
    args = parser.parse_args(argv)
    tool = Maintenance(args.config)
    if args.action in ('release', 'release-plan'):
        from .release_risk import release_risk
        from .rollout import rollout
        from .service_runtime import read_json

        if not args.target or not args.expected_current:
            parser.error('release requires --target and --expected-current')
        if args.action == 'release-plan':
            print(json.dumps(release_risk(tool.profile.source_root, args.expected_current, args.target)))
            return 0
        if not args.ci_run or not args.operation_id:
            parser.error('release requires --ci-run and --operation-id')
        try:
            result = rollout(tool, args.target, args.expected_current, args.ci_run, args.operation_id,
                             review=read_json(args.review) if args.review else None)
        except PreconditionError as exc:
            print(json.dumps({'state': 'BLOCKED', 'reason': str(exc)}))
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['state'] == 'COMPLETED' else 1
    if args.action == 'status':
        status = tool.status()
        print(json.dumps({
            'service': status['service'].get('state'),
            'release': status['current'].get('source_head'),
            'pid': status['service'].get('pid'),
            'maintenance_paused': (tool.root / 'BCT_MAINTENANCE.PAUSE').is_file(),
            'preserved_history': status['database'],
        }, ensure_ascii=False, indent=2))
        return 0
    # One invocation has one readable operation prefix; failures stop here.
    prefix = 'operator-' + uuid.uuid4().hex
    if args.action == 'start':
        result = start(tool, prefix)
        print(json.dumps({'state': 'COMPLETED', 'action': 'start',
                          'journal': str(tool.root / 'maintenance'), **result}, indent=2))
        return 0
    def run(action, **kwargs):
        return tool.run(action, operation_id=prefix+'-'+action,
                        expected_current=tool.current_pointer()['source_head'], **kwargs)
    if args.action == 'recover':
        if not args.target:
            parser.error('recover requires --target (verified release SHA)')
        tool.verify(args.target)
    if not (tool.root / 'BCT_MAINTENANCE.PAUSE').is_file():
        run('pause')
    if args.action in ('restart', 'stop', 'recover'):
        state = tool.controller.inspect()
        if state['state'] == 'RUNNING':
            run('stop')
    if args.action == 'recover':
        run('recover', target=args.target, resolves=args.resolves)
    elif args.action == 'restart':
        run('start')
    if args.action != 'stop':
        run('resume')
    print(json.dumps({'state': 'COMPLETED', 'action': args.action,
                      'receipt_prefix': prefix, 'journal': str(tool.root / 'maintenance')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

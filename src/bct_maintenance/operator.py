"""Small human-facing entry point for the independently installed tool."""
import argparse
import json
import uuid

from .cli import Maintenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('action', choices=('status', 'restart', 'stop', 'start', 'recover'))
    parser.add_argument('--target')
    parser.add_argument('--resolves')
    args = parser.parse_args(argv)
    tool = Maintenance(args.config)
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
    elif args.action in ('restart', 'start'):
        run('start')
    if args.action != 'stop':
        run('resume')
    print(json.dumps({'state': 'COMPLETED', 'action': args.action,
                      'receipt_prefix': prefix, 'journal': str(tool.root / 'maintenance')}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

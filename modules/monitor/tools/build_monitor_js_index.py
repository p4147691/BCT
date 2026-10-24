from pathlib import Path
import argparse
import hashlib
import re

def main():
    parser = argparse.ArgumentParser(description='Build monitor.js function index')
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root)
    source = root / 'extension' / 'monitor.js'
    output = root / 'extension' / 'MONITOR_JS_INDEX.md'
    raw = source.read_bytes()
    lines = raw.decode('utf-8', errors='replace').splitlines()
    funcs = []
    for lineno, line in enumerate(lines, 1):
        m = re.match(r'^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', line)
        if m:
            funcs.append((lineno, m.group(1)))
    sha = hashlib.sha256(raw).hexdigest()
    tick = chr(96)
    source_label = Path('modules') / 'monitor' / 'extension' / 'monitor.js'
    out = ['# Monitor JS Function Index', '', 'Generated from the deployed runtime. Do not edit by hand.', '',
           f'- source: {tick}{source_label}{tick}', f'- sha256: {tick}{sha}{tick}',
           f'- line count: {len(lines)}', f'- declared functions: {len(funcs)}', '',
           'Search by function name first; line numbers are snapshot hints only.', '']
    step = 5000
    for start in range(1, len(lines)+1, step):
        end = min(len(lines), start+step-1)
        chunk = [(ln, name) for ln, name in funcs if start <= ln <= end]
        out += [f'## Lines {start}-{end}', '']
        if not chunk:
            out += ['(no top-level function declarations detected)', '']
            continue
        for ln, name in chunk:
            out.append(f'- {tick}{name}{tick} — line {ln}')
        out.append('')
    output.write_text('\n'.join(out), encoding='utf-8', newline='\n')
    print(f'WROTE {output} sha256={sha} functions={len(funcs)} lines={len(lines)}')

if __name__ == '__main__':
    main()

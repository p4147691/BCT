"""Fail closed when a changed extension payload reuses its release identity."""
from __future__ import annotations
import argparse
import json
import re
import subprocess

TARGETS = ("rcc", "monitor")


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9]\d*)(\.(0|[1-9]\d*)){0,3}", value):
        raise ValueError("INVALID_NUMERIC_VERSION")
    parts = tuple(int(x) for x in value.split("."))
    if any(x > 65535 for x in parts) or not any(parts):
        raise ValueError("INVALID_NUMERIC_VERSION")
    return parts + (0,) * (4 - len(parts))


def validate_identity(before, after, *, before_builds=(), after_builds=()):
    if version(after.get("version")) <= version(before.get("version")):
        raise ValueError("EXTENSION_VERSION_NOT_INCREASED")
    name = after.get("version_name", "")
    if name != after["version"] and not name.startswith(after["version"] + " "):
        raise ValueError("VERSION_NAME_MISMATCH")
    if before_builds or after_builds:
        if (len(after_builds) != 2 or not all(after_builds)
                or len(set(after_builds)) != 1
                or after_builds[0] in before_builds):
            raise ValueError("RCC_BUILD_ID_NOT_UPDATED_OR_INCONSISTENT")


def check(base, head, git):
    rows = []
    for target in TARGETS:
        root = f"modules/{target}/extension/"
        changed = git("diff", "--name-only", base, head, "--", root).splitlines()
        payload = [p for p in changed if not p.endswith((".md", ".txt"))]
        if not payload:
            rows.append({"target": target, "status": "UNCHANGED"})
            continue
        before = json.loads(git("show", base + ":" + root + "manifest.json"))
        after = json.loads(git("show", head + ":" + root + "manifest.json"))
        builds = []
        if target == "rcc":
            for ref in (base, head):
                values = []
                for file, symbol in (("boot/platform_context.js", "RCC_BACKGROUND_BUILD_ID"),
                                     ("content/conversation_dom.js", "RCC_BUILD_VERSION")):
                    text = git("show", ref + ":" + root + file)
                    matches = re.findall(r"const\s+" + symbol + r"\s*=\s*['\"]([^'\"]+)['\"]", text)
                    if len(matches) != 1:
                        raise ValueError("RCC_BUILD_ID_NOT_UNIQUE")
                    values.append(matches[0])
                builds.append(tuple(values))
        validate_identity(before, after,
                          before_builds=builds[0] if builds else (),
                          after_builds=builds[1] if builds else ())
        rows.append({"target": target, "status": "VERSION_INCREASED",
                     "before": before["version"], "after": after["version"]})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    def git(*argv):
        return subprocess.check_output(["git", *argv], text=True, encoding="utf-8")
    # Resolve refs to immutable commits before examining any files.
    base = git("rev-parse", "--verify", args.base + "^{commit}").strip()
    head = git("rev-parse", "--verify", args.head + "^{commit}").strip()
    print(json.dumps({"base": base, "head": head, "targets": check(base, head, git)}))


if __name__ == "__main__":
    main()

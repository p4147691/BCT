"""Read-only ACL and account boundary audit; does not issue approvals."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from bct.core.approval_boundary import (
    load_protected_issuer_manifest, require_core_boundary,
    require_issuer_boundary,
)
from bct.core.models import AuthorizationError


def audit(role: str, *, policy: Path | None, state: Path | None,
          manifest: Path | None, key: Path | None, issuer: Path | None) -> dict:
    try:
        if role == "core":
            if policy is None or state is None:
                raise AuthorizationError("P2_AUDIT_POLICY_AND_STATE_REQUIRED")
            config = tomllib.loads(policy.read_text(encoding="utf8"))
            approved = config.get("approval_verifier", {})
            if approved.get("enabled") is not True:
                raise AuthorizationError("P2_AUDIT_APPROVAL_DISABLED")
            require_core_boundary(approved.get("boundary"),
                                  policy_path=policy, state_path=state)
        elif role == "approver":
            if manifest is None or key is None or issuer is None:
                raise AuthorizationError("P2_AUDIT_ISSUER_PATHS_REQUIRED")
            config = load_protected_issuer_manifest(manifest)
            require_issuer_boundary(config, issuer_module=issuer, issuer_key=key)
        else:
            raise AuthorizationError("P2_AUDIT_ROLE_INVALID")
        return {"status": "PASS", "role": role, "read_only": True,
                "requires_cross_token_attack_acceptance": True}
    except (AuthorizationError, OSError, ValueError, KeyError) as exc:
        if isinstance(exc, AuthorizationError):
            reason = str(exc)
        else:
            reason = "P2_AUDIT_UNOBSERVABLE"
        return {"status": "BLOCKED", "role": role, "read_only": True,
                "reason": reason}


def main():
    parser = argparse.ArgumentParser(description="BCT P2 ACL audit (read-only)")
    parser.add_argument("--role", choices=("core", "approver"), required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--issuer", type=Path)
    parser.add_argument("--key", type=Path)
    args = parser.parse_args()
    result = audit(args.role, policy=args.policy, state=args.state,
                   manifest=args.manifest, issuer=args.issuer, key=args.key)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())

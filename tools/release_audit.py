#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded, case-insensitive namespace audit for release inputs."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import stat
from collections.abc import Iterable, Sequence
from typing import Any


CHUNK_BYTES = 1024 * 1024
MAX_FINDINGS = 256
EXCLUDED_DIRECTORY_NAMES = frozenset({".git"})


class ReleaseAuditError(RuntimeError):
    """A release input cannot be audited safely or contains a forbidden term."""


@dataclasses.dataclass(frozen=True)
class ForbiddenPattern:
    raw: bytes
    folded: bytes
    sha256: str


@dataclasses.dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    pattern_sha256: str


def _patterns(values: Sequence[str]) -> tuple[ForbiddenPattern, ...]:
    found: dict[bytes, ForbiddenPattern] = {}
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ReleaseAuditError("forbidden terms must be non-empty and trimmed")
        try:
            raw = value.encode("ascii")
        except UnicodeEncodeError as error:
            raise ReleaseAuditError("forbidden terms must be ASCII") from error
        folded = raw.lower()
        if any(byte < 0x20 or byte > 0x7E for byte in raw):
            raise ReleaseAuditError("forbidden terms must contain printable ASCII only")
        found.setdefault(
            folded,
            ForbiddenPattern(
                raw=raw,
                folded=folded,
                sha256=hashlib.sha256(raw).hexdigest(),
            ),
        )
    if not found:
        raise ReleaseAuditError("at least one forbidden term is required")
    return tuple(found[key] for key in sorted(found))


def _relative_label(root: pathlib.Path, path: pathlib.Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ReleaseAuditError(f"audit path escapes its root: {path}") from error
    return "." if relative == pathlib.Path() else relative.as_posix()


def _matches(value: bytes, patterns: Sequence[ForbiddenPattern]) -> list[ForbiddenPattern]:
    folded = value.lower()
    return [pattern for pattern in patterns if pattern.folded in folded]


def _content_matches(
    path: pathlib.Path,
    patterns: Sequence[ForbiddenPattern],
) -> list[ForbiddenPattern]:
    maximum = max(len(pattern.folded) for pattern in patterns)
    overlap = max(0, maximum - 1)
    matched: dict[str, ForbiddenPattern] = {}
    tail = b""
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK_BYTES)
                if not chunk:
                    break
                window = tail + chunk
                for pattern in _matches(window, patterns):
                    matched[pattern.sha256] = pattern
                tail = window[-overlap:] if overlap else b""
    except OSError as error:
        raise ReleaseAuditError(f"cannot read release input {path}: {error}") from error
    return [matched[key] for key in sorted(matched)]


def _append(
    findings: list[Finding],
    *,
    kind: str,
    path: str,
    patterns: Iterable[ForbiddenPattern],
) -> None:
    existing = {(item.kind, item.path, item.pattern_sha256) for item in findings}
    for pattern in patterns:
        key = (kind, path, pattern.sha256)
        if key in existing:
            continue
        if len(findings) >= MAX_FINDINGS:
            raise ReleaseAuditError(
                f"release audit exceeded the bounded finding limit ({MAX_FINDINGS})"
            )
        findings.append(Finding(kind, path, pattern.sha256))
        existing.add(key)


def _walk(root: pathlib.Path) -> Iterable[pathlib.Path]:
    pending = [root]
    while pending:
        current = pending.pop()
        yield current
        try:
            mode = current.lstat().st_mode
        except OSError as error:
            raise ReleaseAuditError(f"cannot inspect release input {current}: {error}") from error
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            continue
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name, reverse=True)
        except OSError as error:
            raise ReleaseAuditError(f"cannot enumerate release input {current}: {error}") from error
        pending.extend(
            child
            for child in children
            if not (child.is_dir() and child.name in EXCLUDED_DIRECTORY_NAMES)
        )


def audit_paths(paths: Sequence[pathlib.Path], forbidden: Sequence[str]) -> dict[str, Any]:
    """Audit paths, names, symlink targets, and bytes without following symlinks."""
    patterns = _patterns(forbidden)
    if not paths:
        raise ReleaseAuditError("at least one release input path is required")
    findings: list[Finding] = []
    files = 0
    directories = 0
    symlinks = 0
    other = 0
    roots: list[str] = []
    for requested in paths:
        root = requested.expanduser().resolve(strict=True)
        roots.append(str(root))
        for path in _walk(root):
            label = _relative_label(root, path)
            _append(
                findings,
                kind="path",
                path=label,
                patterns=_matches(label.encode("utf-8", "surrogateescape"), patterns),
            )
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                symlinks += 1
                try:
                    target = os.readlink(path).encode("utf-8", "surrogateescape")
                except OSError as error:
                    raise ReleaseAuditError(
                        f"cannot read release symlink {path}: {error}"
                    ) from error
                _append(
                    findings,
                    kind="symlink",
                    path=label,
                    patterns=_matches(target, patterns),
                )
            elif stat.S_ISREG(mode):
                files += 1
                _append(
                    findings,
                    kind="content",
                    path=label,
                    patterns=_content_matches(path, patterns),
                )
            elif stat.S_ISDIR(mode):
                directories += 1
            else:
                other += 1
    findings.sort(key=lambda item: (item.path, item.kind, item.pattern_sha256))
    return {
        "schema_version": 1,
        "clean": not findings,
        "roots": roots,
        "patterns": [pattern.sha256 for pattern in patterns],
        "counts": {
            "directories": directories,
            "files": files,
            "symlinks": symlinks,
            "other": other,
            "findings": len(findings),
        },
        "findings": [dataclasses.asdict(item) for item in findings],
    }


def render_result(result: dict[str, Any], *, json_output: bool) -> str:
    if json_output:
        return json.dumps(result, sort_keys=True, separators=(",", ":"))
    counts = result["counts"]
    status = "PASS" if result["clean"] else "FAIL"
    lines = [
        f"{status} release-audit files={counts['files']} directories={counts['directories']} "
        f"symlinks={counts['symlinks']} findings={counts['findings']}"
    ]
    lines.extend(
        f"{item['kind']} {item['path']} pattern_sha256={item['pattern_sha256']}"
        for item in result["findings"]
    )
    return "\n".join(lines)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="scan release inputs for forbidden namespace material"
    )
    parser.add_argument(
        "--forbid",
        dest="forbidden",
        action="append",
        required=True,
        help="printable ASCII term to reject; repeat for multiple terms",
    )
    parser.add_argument("paths", nargs="+", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(arguments)
    try:
        result = audit_paths(parsed.paths, parsed.forbidden)
    except ReleaseAuditError as error:
        parser.error(str(error))
    print(render_result(result, json_output=parsed.json))
    return 0 if result["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

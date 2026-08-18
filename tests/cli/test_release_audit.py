#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import contextlib
import io
import pathlib
import tempfile
import unittest

from tools.release_audit import CHUNK_BYTES, ReleaseAuditError, audit_paths, main


class ReleaseAuditTests(unittest.TestCase):
    def test_command_returns_failure_for_a_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "input.txt").write_text("retired namespace")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--forbid", "retired", str(root)]), 1)

    def test_clean_tree_counts_files_directories_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "source").mkdir()
            (root / "source" / "module.py").write_text("clean\n", encoding="utf-8")
            (root / "launcher").symlink_to("source/module.py")
            result = audit_paths([root], ["retiredbrand"])
        self.assertTrue(result["clean"])
        self.assertEqual(result["counts"]["files"], 1)
        self.assertEqual(result["counts"]["symlinks"], 1)
        self.assertEqual(result["counts"]["findings"], 0)

    def test_case_insensitive_path_content_and_symlink_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "RetiredBrand.txt").write_text("RETIReDBrand\n", encoding="utf-8")
            (root / "link").symlink_to("retiredbrand-target")
            result = audit_paths([root], ["retiredbrand"])
        self.assertFalse(result["clean"])
        self.assertEqual(
            {(item["kind"], item["path"]) for item in result["findings"]},
            {
                ("path", "RetiredBrand.txt"),
                ("content", "RetiredBrand.txt"),
                ("symlink", "link"),
            },
        )

    def test_binary_match_across_chunk_boundary_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            prefix = b"x" * (CHUNK_BYTES - 4)
            (root / "artifact.bin").write_bytes(prefix + b"retiredbrand")
            result = audit_paths([root], ["retiredbrand"])
        self.assertFalse(result["clean"])
        self.assertEqual(result["findings"][0]["kind"], "content")

    def test_nested_git_metadata_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            metadata = root / "nested" / ".git"
            metadata.mkdir(parents=True)
            (metadata / "log").write_text("retiredbrand\n", encoding="utf-8")
            result = audit_paths([root], ["retiredbrand"])
        self.assertTrue(result["clean"])

    def test_invalid_terms_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for value in ("", " untrimmed", "snowman-☃"):
                with self.subTest(value=value), self.assertRaises(ReleaseAuditError):
                    audit_paths([root], [value])


if __name__ == "__main__":
    unittest.main()

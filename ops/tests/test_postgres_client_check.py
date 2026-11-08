import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


class PostgresClientCompatibilityTests(TestCase):
    def check_versions(self, server, dump, restore):
        helper = Path(__file__).resolve().parents[1] / "postgres-client-check.sh"
        with TemporaryDirectory() as tmp:
            for name, value in [("psql", server), ("pg_dump", f"pg_dump (PostgreSQL) {dump}.0"),
                                ("pg_restore", f"pg_restore (PostgreSQL) {restore}.0")]:
                executable = Path(tmp) / name
                executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{value}'\n")
                executable.chmod(0o700)
            return subprocess.run(
                ["/bin/bash", "-c", 'source "$1"; require_matching_postgres_clients', "preflight", str(helper)],
                env={**os.environ, "PATH": tmp}, text=True, capture_output=True, timeout=5, check=False,
            )

    def test_matching_major_is_accepted(self):
        self.assertEqual(self.check_versions("160013", 16, 16).returncode, 0)

    def test_newer_dump_client_is_refused_before_dump_or_restore(self):
        result = self.check_versions("160013", 18, 18)
        self.assertEqual(result.returncode, 2)
        self.assertIn("must match PostgreSQL server major 16", result.stderr)

    def test_mixed_restore_client_is_refused(self):
        self.assertEqual(self.check_versions("160013", 16, 18).returncode, 2)

    def test_invalid_version_is_refused(self):
        self.assertEqual(self.check_versions("invalid", 16, 16).returncode, 2)

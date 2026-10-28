"""Pure Python, offline tests for host runner. No Docker invocation occurs."""
import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("obs_quality_host_runner", Path(__file__).with_name("host_runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class HostRunnerSafetyTests(TestCase):
    def test_allowlist_excludes_redis_and_web(self):
        self.assertEqual(runner.SAFE_TARGETS, {"celery_worker", "celery_beat"})
        self.assertNotIn("redis", runner.SAFE_TARGETS)
        self.assertNotIn("web", runner.SAFE_TARGETS)

    def test_dry_run_never_executes_restart(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manage.py").write_text("# synthetic")
            with patch.object(runner, "bridge", return_value={"pending": []}) as bridge, \
                 patch.object(runner, "call") as call, \
                 patch.object(runner.shutil, "which", return_value="/usr/bin/docker"), \
                 patch.object(runner, "ROOT", root), \
                 patch.object(runner, "Path", side_effect=lambda _: SimpleNamespace(exists=lambda: False)), \
                 patch("sys.argv", ["host_runner.py", "--dry-run"]):
                runner.main()
            bridge.assert_called_once_with("peek")
            call.assert_not_called()

    def test_success_path_uses_fixed_compose_target_and_reports_token(self):
        """Only approved target reaches compose restart; token never enters argv."""
        calls = []
        class Result:
            returncode = 0
            stdout = "running-container-id\n"
        def fake_call(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if "inspect" in cmd:
                return type("R", (), {"returncode": 0, "stdout": "true\n"})()
            return Result()
        def fake_bridge(verb, *args, **kwargs):
            if verb == "claim":
                return {"operation": {"id": "safe-uuid", "target": "celery_beat"}, "token": "FAKE-ONE-TIME-TOKEN"}
            if verb == "complete":
                self.assertEqual(kwargs["input"], "FAKE-ONE-TIME-TOKEN\n")
                self.assertNotIn("FAKE-ONE-TIME-TOKEN", repr(args))
                return {"status": "succeeded"}
            raise AssertionError(verb)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manage.py").write_text("# synthetic")
            lock_dir = root / "lock"
            with patch.object(runner, "bridge", side_effect=fake_bridge), \
                 patch.object(runner, "call", side_effect=fake_call), \
                 patch.object(runner.shutil, "which", return_value="/usr/bin/docker"), \
                 patch.object(runner, "ROOT", root), \
                 patch.object(runner, "Path", side_effect=lambda _: SimpleNamespace(exists=lambda: False)), \
                 patch.object(runner, "LOCK_DIR", lock_dir), \
                 patch.object(runner, "LOCK", lock_dir / "test.lock"), \
                 patch("sys.argv", ["host_runner.py"]):
                runner.main()
        restart_commands = [args for args, _ in calls if "restart" in args]
        self.assertEqual(len(restart_commands), 1)
        self.assertEqual(restart_commands[0][-2:], ["restart", "celery_beat"])

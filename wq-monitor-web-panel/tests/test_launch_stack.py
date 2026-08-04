import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quant_worker_monitor_panel.launch_stack import build_launch_targets, launch_targets, main


PROJECT_RUNTIME = Path("E:/Quant worker-CLEAN/wq-alpha-research/project_runtime.py")
ADAPTER_HOST = Path("E:/Quant worker-monitor-web-panel/adapter_host.py")
PANEL_APP = Path("E:/Quant worker-monitor-web-panel/panel_app.py")
PYTHON = Path("E:/Python311/python.exe")


class LaunchStackTests(unittest.TestCase):
    def test_build_launch_targets_defaults_to_canonical_full_chain_mode(self):
        targets = build_launch_targets(PYTHON, PROJECT_RUNTIME, PANEL_APP)

        # Adapter host carries the canonical run mode to the project runtime it spawns.
        self.assertEqual(targets[0].env_overrides["QUANT WORKER_RUN_MODE"], "research+submit")

    def test_build_launch_targets_marks_single_instance_lock_names(self):
        targets = build_launch_targets(PYTHON, PROJECT_RUNTIME, PANEL_APP)

        self.assertEqual(targets[0].lock_name, "quant_worker_adapter_host")
        self.assertEqual(targets[1].lock_name, "quant_worker_project_runtime")
        self.assertEqual(targets[2].lock_name, "quant_worker_panel_app")

    def test_build_launch_targets_orders_adapter_then_project_then_panel(self):
        targets = build_launch_targets(PYTHON, PROJECT_RUNTIME, PANEL_APP)

        self.assertEqual(
            [t.script.name for t in targets],
            ["adapter_host.py", "project_runtime.py", "panel_app.py"],
        )
        self.assertEqual(targets[0].cwd, Path("E:/Quant worker-monitor-web-panel"))
        self.assertEqual(targets[1].cwd, Path("E:/Quant worker-CLEAN/wq-alpha-research"))
        self.assertEqual(targets[2].cwd, Path("E:/Quant worker-monitor-web-panel"))
        self.assertTrue(targets[0].supervise)
        self.assertTrue(targets[1].supervise)
        self.assertTrue(targets[2].supervise)

    def test_build_launch_targets_carries_canonical_run_mode_for_full_chain(self):
        targets = build_launch_targets(
            PYTHON,
            PROJECT_RUNTIME,
            PANEL_APP,
            run_mode="research+submit",
        )

        self.assertEqual(targets[0].env_overrides["QUANT WORKER_RUN_MODE"], "research+submit")
        self.assertEqual(targets[1].env_overrides["QUANT WORKER_RUN_MODE"], "research+submit")
        self.assertNotIn("QUANT WORKER_RUN_MODE", targets[2].env_overrides)

    def test_launch_targets_passes_canonical_run_mode_to_project_runtime_process(self):
        adapter_target, runtime_target, panel_target = build_launch_targets(
            PYTHON,
            PROJECT_RUNTIME,
            PANEL_APP,
            run_mode="research+submit",
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "quant_worker_monitor_panel.launch_stack.LOCK_DIR", Path(tmpdir)
        ), mock.patch(
            "quant_worker_monitor_panel.launch_stack.list_active_python_pids", return_value=set()
        ), mock.patch("quant_worker_monitor_panel.launch_stack.subprocess.Popen") as popen:
            launch_targets(PYTHON, [adapter_target, runtime_target, panel_target])

        adapter_env = popen.call_args_list[0].kwargs["env"]
        runtime_env = popen.call_args_list[1].kwargs["env"]
        panel_env = popen.call_args_list[2].kwargs["env"]
        self.assertEqual(adapter_env["QUANT WORKER_RUN_MODE"], "research+submit")
        self.assertEqual(runtime_env["QUANT WORKER_RUN_MODE"], "research+submit")
        self.assertNotIn("QUANT WORKER_RUN_MODE", panel_env)

    def test_main_uses_project_runtime_default_path(self):
        adapter_target = mock.Mock(
            label="适配器主机",
            script=ADAPTER_HOST,
            cwd=ADAPTER_HOST.parent,
        )
        runtime_target = mock.Mock(
            label="项目运行时",
            script=PROJECT_RUNTIME,
            cwd=PROJECT_RUNTIME.parent,
        )
        panel_target = mock.Mock(
            label="监控面板",
            script=PANEL_APP,
            cwd=PANEL_APP.parent,
        )

        with mock.patch(
            "quant_worker_monitor_panel.launch_stack.build_launch_targets",
            return_value=[adapter_target, runtime_target, panel_target],
        ) as build_targets, mock.patch(
            "quant_worker_monitor_panel.launch_stack.split_existing_and_missing",
            return_value=([adapter_target, runtime_target, panel_target], []),
        ), mock.patch(
            "quant_worker_monitor_panel.launch_stack.launch_and_wait",
            return_value=7,
        ) as launch_and_wait:
            rc = main()

        self.assertEqual(rc, 7)
        build_targets.assert_called_once()
        self.assertEqual(Path(build_targets.call_args.args[1]).name, "project_runtime.py")
        launch_and_wait.assert_called_once_with(
            [adapter_target, runtime_target, panel_target]
        )

    def test_main_refuses_partial_start_when_project_runtime_missing(self):
        adapter_target = mock.Mock(
            label="适配器主机",
            script=ADAPTER_HOST,
            cwd=ADAPTER_HOST.parent,
        )
        runtime_target = mock.Mock(
            label="项目运行时",
            script=PROJECT_RUNTIME,
            cwd=PROJECT_RUNTIME.parent,
        )
        panel_target = mock.Mock(
            label="监控面板",
            script=PANEL_APP,
            cwd=PANEL_APP.parent,
        )

        with mock.patch(
            "quant_worker_monitor_panel.launch_stack.build_launch_targets",
            return_value=[adapter_target, runtime_target, panel_target],
        ), mock.patch(
            "quant_worker_monitor_panel.launch_stack.split_existing_and_missing",
            return_value=([panel_target], [adapter_target, runtime_target]),
        ), mock.patch(
            "quant_worker_monitor_panel.launch_stack.launch_and_wait",
        ) as launch_and_wait, mock.patch(
            "quant_worker_monitor_panel.launch_stack.launch_targets",
        ) as raw_launch_targets:
            rc = main()

        self.assertNotEqual(rc, 0)
        launch_and_wait.assert_not_called()
        raw_launch_targets.assert_not_called()


if __name__ == "__main__":
    unittest.main()

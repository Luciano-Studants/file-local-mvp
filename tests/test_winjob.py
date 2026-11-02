"""Job Object do Windows (0.9.26): estruturas e sequência de chamadas conferidas com um kernel32 falso; a execução real só é possível no Windows."""
import ctypes
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runner
import winjob


class LayoutTests(unittest.TestCase):
    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, 'layout de 64 bits')
    def test_structure_sizes_match_the_windows_x64_headers(self):
        self.assertEqual(ctypes.sizeof(winjob.BasicLimits), 64)
        self.assertEqual(ctypes.sizeof(winjob.IoCounters), 48)
        self.assertEqual(ctypes.sizeof(winjob.ExtendedLimits), 144)
        self.assertEqual(winjob.ExtendedLimits.ProcessMemoryLimit.offset, 112)

    def test_limits_values(self):
        limits = winjob.build_limits()
        flags = limits.BasicLimitInformation.LimitFlags
        for flag in (winjob.JOB_OBJECT_LIMIT_PROCESS_MEMORY, winjob.JOB_OBJECT_LIMIT_ACTIVE_PROCESS, winjob.JOB_OBJECT_LIMIT_PROCESS_TIME, winjob.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE):
            self.assertTrue(flags & flag)
        self.assertEqual((limits.ProcessMemoryLimit, limits.BasicLimitInformation.ActiveProcessLimit), (3 * 1024 ** 3, 4))
        self.assertEqual(limits.BasicLimitInformation.PerProcessUserTimeLimit, 170 * 10_000_000)
        custom = winjob.build_limits(memory=1 << 30, processes=2, cpu_seconds=10)
        self.assertEqual((custom.ProcessMemoryLimit, custom.BasicLimitInformation.ActiveProcessLimit), (1 << 30, 2))


class AttachTests(unittest.TestCase):
    def fake(self, **overrides):
        kernel = MagicMock(); kernel.CreateJobObjectW.return_value = 77; kernel.SetInformationJobObject.return_value = 1; kernel.AssignProcessToJobObject.return_value = 1
        for key, value in overrides.items(): getattr(kernel, key).return_value = value
        return kernel

    def test_call_sequence(self):
        kernel = self.fake(); process = MagicMock(); process._handle = 1234
        self.assertEqual(winjob.attach(process, kernel), 77)
        order = [call[0] for call in kernel.method_calls]
        self.assertEqual(order, ['CreateJobObjectW', 'SetInformationJobObject', 'AssignProcessToJobObject'])
        args = kernel.SetInformationJobObject.call_args.args
        self.assertEqual((args[0], args[1], args[3]), (77, 9, 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.sizeof(winjob.ExtendedLimits)))
        self.assertEqual(kernel.AssignProcessToJobObject.call_args.args, (77, 1234)); self.assertEqual(winjob.last_error, '')

    def test_each_failure_returns_none_closes_the_handle_and_explains(self):
        for failing, text in (('CreateJobObjectW', 'CreateJobObjectW'), ('SetInformationJobObject', 'SetInformationJobObject'), ('AssignProcessToJobObject', 'AssignProcessToJobObject')):
            kernel = self.fake(**{failing: 0}); process = MagicMock(); process._handle = 5
            self.assertIsNone(winjob.attach(process, kernel)); self.assertIn(text, winjob.last_error)
            self.assertEqual(kernel.CloseHandle.called, failing != 'CreateJobObjectW')
        process = MagicMock(spec=[]); kernel = self.fake()
        self.assertIsNone(winjob.attach(process, kernel)); self.assertTrue(kernel.CloseHandle.called)

    @unittest.skipIf(os.name == 'nt', 'testa o caminho fora do Windows')
    def test_not_windows_returns_none(self):
        self.assertIsNone(winjob.attach(MagicMock())); self.assertIn('Windows', winjob.last_error)

    def test_release_closes_and_ignores_none(self):
        kernel = self.fake(); winjob.release(77, kernel); kernel.CloseHandle.assert_called_once_with(77)
        winjob.release(None, kernel); self.assertEqual(kernel.CloseHandle.call_count, 1)


class RunnerIntegrationTests(unittest.TestCase):
    def test_runner_attaches_and_releases_on_windows_only(self):
        import tempfile
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'a.png'; Image.new('RGB', (20, 20), 'red').save(src)
            with patch.object(winjob, 'attach', return_value=None) as attach, patch.object(winjob, 'release') as release:
                result = runner.run_job({'paths': [str(src)], 'target': 'PNG', 'output': str(Path(tmp))}, timeout=60)
            self.assertTrue(Path(result[0]).is_file()); self.assertEqual(attach.called, os.name == 'nt'); self.assertTrue(release.called)


if __name__ == '__main__':
    unittest.main()

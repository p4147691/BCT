import asyncio
import ctypes
import gc
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from bct.integrations import rcc
from bct.monitor_events import SnapshotFlight
from bct.features.execution import ExecuteFeature, _MAX_CAPTURE_BYTES
from bct.core.models import Work


class NativeTypeRetentionTests(unittest.TestCase):
    def test_repeated_abi_pointer_lookup_does_not_retain_new_types(self):
        types = (rcc.TokenUser, rcc.TokenGroupsOne, rcc.AceHeader)
        for kind in types:
            ctypes.POINTER(kind)
        before = len(ctypes._pointer_type_cache)
        for _ in range(5000):
            for kind in types:
                ctypes.POINTER(kind)
        gc.collect()
        self.assertEqual(before, len(ctypes._pointer_type_cache))


class SnapshotFlightTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_clients_and_cancel_share_one_build(self):
        flight = SnapshotFlight()
        started = threading.Event()
        release = threading.Event()
        calls = []

        def build():
            calls.append(1)
            started.set()
            release.wait(5)
            return {'revision': len(calls)}

        first = asyncio.create_task(flight.get(build))
        await asyncio.to_thread(started.wait, 5)
        other = asyncio.create_task(flight.get(build))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        self.assertEqual({'revision': 1}, await other)
        self.assertEqual(1, len(calls))
        self.assertIsNone(flight._task)
        self.assertEqual({'revision': 2}, await flight.get(build))

    async def test_failed_snapshot_is_released_and_retry_builds(self):
        flight = SnapshotFlight()
        def fail():
            raise ValueError('fixture')
        with self.assertRaises(ValueError):
            await flight.get(fail)
        self.assertIsNone(flight._task)
        self.assertEqual(7, await flight.get(lambda: 7))


class ExecutionRetentionTests(unittest.TestCase):
    def run_child(self, code, timeout=10):
        with tempfile.TemporaryDirectory() as directory:
            work = Work('fixture', 'fixture', (directory,), frozenset({'execute'}), 'fixture')
            feature = ExecuteFeature()
            request = feature.prepare(work=work, arguments={
                'cwd': directory, 'argv': [sys.executable, '-c', code], 'timeout_s': timeout,
            })
            return feature.execute(request)

    def test_large_stdout_and_stderr_are_clipped_independently(self):
        result = self.run_child("import os; os.write(1,b'a'*(8*1024*1024)); os.write(2,b'b'*(8*1024*1024))")
        self.assertEqual('APPLIED', result.outcome.value)
        for stream, char in [('stdout', 'a'), ('stderr', 'b')]:
            self.assertEqual(char * _MAX_CAPTURE_BYTES, result.output[stream])
            self.assertTrue(result.output[stream + '_truncated'])

    def test_timeout_retains_captured_output(self):
        result = self.run_child("import os,time; os.write(1,b'before-timeout'); time.sleep(10)", timeout=.5)
        self.assertEqual('TIMEOUT', result.evidence['phase'])
        self.assertEqual('before-timeout', result.output['stdout'])
        self.assertTrue(result.evidence['terminated'])

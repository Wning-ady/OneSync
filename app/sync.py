from __future__ import annotations

import asyncio
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SyncManager:
    config_dir: Path
    data_dir: Path
    process: asyncio.subprocess.Process | None = None
    mode: str = "stopped"
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=400))
    _reader: asyncio.Task[None] | None = None
    _resync_task: asyncio.Task[None] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    operation_phase: str = "idle"
    operation_message: str = ""
    operation_error: str | None = None
    operation_started_at: str | None = None
    operation_finished_at: str | None = None

    def _set_operation(self, phase: str, message: str, error: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if phase == "queued":
            self.operation_started_at = now
            self.operation_finished_at = None
        elif phase in {"succeeded", "failed", "cancelled"}:
            self.operation_finished_at = now
        self.operation_phase = phase
        self.operation_message = message
        self.operation_error = error

    def _command(self, *arguments: str) -> list[str]:
        return [
            "onedrive",
            "--confdir",
            str(self.config_dir),
            "--syncdir",
            str(self.data_dir),
            "--force-http-11",
            *arguments,
        ]

    async def _consume_output(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout
        async for line in process.stdout:
            self.logs.append(line.decode(errors="replace").rstrip())
        result = await process.wait()
        self.logs.append(f"OneDrive process exited with code {result}.")
        if self.process is process:
            self.process = None
            self.mode = "stopped"

    async def _wait_with_logs(self, process: asyncio.subprocess.Process) -> int:
        assert process.stdout
        async for line in process.stdout:
            self.logs.append(line.decode(errors="replace").rstrip())
        return await process.wait()

    async def start(self, mode: str = "monitor") -> None:
        async with self._lock:
            if self.process and self.process.returncode is None:
                return
            arguments = ["--monitor"] if mode == "monitor" else ["--sync"]
            self.logs.append("Starting: onedrive " + " ".join(arguments))
            self.process = await asyncio.create_subprocess_exec(
                *self._command(*arguments),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "HOME": str(self.config_dir)},
            )
            self.mode = mode
            self._reader = asyncio.create_task(self._consume_output(self.process))

    async def stop(self) -> None:
        process = self.process
        if not process or process.returncode is not None:
            self.mode = "stopped"
            return
        self.logs.append("Stopping OneDrive process.")
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=20)
        except TimeoutError:
            process.kill()
            await process.wait()
        if self.process is process:
            self.process = None
        self.mode = "stopped"

    async def run_controlled_resync(self) -> None:
        try:
            await self.stop()
            async with self._lock:
                self.mode = "resync"
                self._set_operation("dry_run", "Running safety dry-run.")
                self.logs.append("Running dry-run before resync.")
                dry_run = await asyncio.create_subprocess_exec(
                    *self._command("--sync", "--dry-run", "--resync", "--resync-auth"),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ, "HOME": str(self.config_dir)},
                )
                self.process = dry_run
                if await self._wait_with_logs(dry_run):
                    message = "Dry-run failed; resync was not started."
                    self.logs.append(message)
                    self._set_operation("failed", message, self._last_error())
                    return

                self._set_operation("resync", "Dry-run passed; confirmed resync is running.")
                self.logs.append("Dry-run passed. Running confirmed resync.")
                resync = await asyncio.create_subprocess_exec(
                    *self._command("--sync", "--resync", "--resync-auth"),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ, "HOME": str(self.config_dir)},
                )
                self.process = resync
                if await self._wait_with_logs(resync):
                    message = "Resync failed; monitor remains stopped."
                    self.logs.append(message)
                    self._set_operation("failed", message, self._last_error())
                    return
                self.process = None

            self._set_operation("succeeded", "Resync completed. Continuous monitoring remains stopped.")
            self.logs.append("Resync completed successfully. Continuous monitoring remains stopped.")
        except asyncio.CancelledError:
            self._set_operation("cancelled", "Resync was cancelled.")
            raise
        except Exception as error:
            message = f"Resync control failed: {error}"
            self.logs.append(message)
            self._set_operation("failed", "Resync could not be completed.", str(error))
        finally:
            if self.process and self.process.returncode is not None:
                self.process = None
            if not self.process:
                self.mode = "stopped"

    def _last_error(self) -> str | None:
        for line in reversed(self.logs):
            if "AADSTS" in line or "ERROR" in line or "Exception" in line:
                return line
        return None

    def schedule_resync(self) -> bool:
        if self._resync_task and not self._resync_task.done():
            return False
        self.mode = "resync_pending"
        self._set_operation("queued", "Resync queued; preparing the dry-run.")
        self._resync_task = asyncio.create_task(self.run_controlled_resync())
        return True

    async def shutdown(self) -> None:
        await self.cancel_resync()
        await self.stop()

    async def cancel_resync(self) -> None:
        task = self._resync_task
        if not task or task.done() or task is asyncio.current_task():
            return
        self.logs.append("Cancelling the active resync task.")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def cancel_and_stop(self) -> None:
        await self.cancel_resync()
        await self.stop()

    async def reauth(self) -> None:
        await self.cancel_and_stop()
        async with self._lock:
            self.logs.append("Starting OneDrive reauthorization. Complete the device-code prompt below.")
            self.process = await asyncio.create_subprocess_exec(
                *self._command("--reauth"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "HOME": str(self.config_dir)},
            )
            self.mode = "reauth"
            self._reader = asyncio.create_task(self._consume_output(self.process))

    def status(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "running": bool(self.process and self.process.returncode is None),
            "dataDirectory": str(self.data_dir),
            "configDirectory": str(self.config_dir),
            "operation": {
                "phase": self.operation_phase,
                "message": self.operation_message,
                "error": self.operation_error,
                "startedAt": self.operation_started_at,
                "finishedAt": self.operation_finished_at,
            },
        }

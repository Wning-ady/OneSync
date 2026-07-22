from __future__ import annotations

import asyncio
import json
import os
import re
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
    events: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=500))
    completed_downloads: int = 0
    completed_uploads: int = 0
    active_download: str | None = None
    active_upload: str | None = None
    _last_failed_path: str | None = None

    def _event_path(self) -> Path:
        return self.config_dir / "change-events.jsonl"

    def _record(self, direction: str, action: str, path: str = "", status: str = "completed", detail: str = "") -> None:
        event = {"time": datetime.now(timezone.utc).isoformat(), "direction": direction, "action": action, "path": path, "status": status, "detail": detail, "mode": self.mode}
        self.events.append(event)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with self._event_path().open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _append_log(self, line: str) -> None:
        self.logs.append(line)
        download = re.search(r"^Downloading file: (.+?) \.\.\. (done|failed!)$", line)
        upload = re.search(r"^Uploading (?:new |modified )?file: (.+?) \.\.\. (done|failed!)$", line)
        progress = re.search(r"^Downloading: (.+?) \.\.\. (\d+)%", line)
        if progress:
            self.active_download = progress.group(1)
        if download:
            path, outcome = download.groups()
            self.active_download = None
            if outcome == "done":
                self.completed_downloads += 1
                self._record("cloud_to_local", "download", path)
            else:
                self._last_failed_path = path
                self._record("cloud_to_local", "download", path, "failed", "下载失败，正在确认原因")
        elif upload:
            path, outcome = upload.groups()
            self.active_upload = None
            if outcome == "done":
                self.completed_uploads += 1
                self._record("local_to_cloud", "upload", path)
            else:
                self._record("local_to_cloud", "upload", path, "failed", "上传失败")
        elif line.startswith("Deleting remote file:"):
            self._record("local_to_cloud", "delete", line.split(":", 1)[1].strip())
        elif line.startswith("Deleting local file:"):
            self._record("cloud_to_local", "delete", line.split(":", 1)[1].strip())
        elif "Conflict" in line:
            self._record("conflict", "conflict", status="warning", detail=line)
        elif "status code 404" in line and self._last_failed_path:
            self._record("cloud_to_local", "remote_missing", self._last_failed_path, "warning", "云端对象已删除或移动；未自动删除本地文件")
            self._last_failed_path = None

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
            self._append_log(line.decode(errors="replace").rstrip())
        result = await process.wait()
        self._append_log(f"OneDrive process exited with code {result}.")
        if result:
            self._record("system", "engine_exit", status="failed", detail=f"OneDrive exited with code {result}")
        if self.process is process:
            self.process = None
            self.mode = "stopped"

    async def _wait_with_logs(self, process: asyncio.subprocess.Process) -> int:
        assert process.stdout
        async for line in process.stdout:
            self._append_log(line.decode(errors="replace").rstrip())
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
            "progress": {"downloadsCompleted": self.completed_downloads, "uploadsCompleted": self.completed_uploads, "activeDownload": self.active_download, "activeUpload": self.active_upload, "totalKnown": False},
        }

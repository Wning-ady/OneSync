import asyncio

import pytest

from app.sync import SyncManager


def test_resync_is_queued_only_once(tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")

    async def scenario() -> None:
        blocker = asyncio.Event()

        async def controlled() -> None:
            await blocker.wait()

        manager.run_controlled_resync = controlled  # type: ignore[method-assign]
        assert manager.schedule_resync() is True
        assert manager.schedule_resync() is False
        assert manager.status()["operation"]["phase"] == "queued"  # type: ignore[index]
        blocker.set()
        await manager._resync_task

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_resync_exception_is_reported(monkeypatch, tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")

    async def fail(*args, **kwargs):
        raise OSError("cannot start client")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail)
    manager.schedule_resync()
    await manager._resync_task

    operation = manager.status()["operation"]
    assert operation["phase"] == "failed"  # type: ignore[index]
    assert operation["error"] == "cannot start client"  # type: ignore[index]
    assert any("cannot start client" in line for line in manager.logs)


@pytest.mark.asyncio
async def test_cancel_and_stop_cancels_active_resync(tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")
    started = asyncio.Event()

    async def controlled() -> None:
        started.set()
        await asyncio.Event().wait()

    manager.run_controlled_resync = controlled  # type: ignore[method-assign]
    assert manager.schedule_resync() is True
    await started.wait()

    await manager.cancel_and_stop()

    assert manager._resync_task is not None
    assert manager._resync_task.cancelled()
    assert manager.mode == "stopped"


@pytest.mark.asyncio
async def test_successful_resync_does_not_start_monitor(monkeypatch, tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")

    class Process:
        stdout = None
        returncode = 0

        async def wait(self):
            return 0

    async def create_process(*args, **kwargs):
        return Process()

    async def successful_wait(process):
        return 0

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(manager, "_wait_with_logs", successful_wait)
    await manager.run_controlled_resync()

    assert manager.status()["operation"]["phase"] == "succeeded"  # type: ignore[index]
    assert manager.mode == "stopped"


@pytest.mark.asyncio
async def test_download_metrics_read_partial_file(tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")
    partial = manager.data_dir / "docs" / "archive.bin.partial"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"x" * 100)
    manager._append_log("Downloading: docs/archive.bin ... 5%")
    await asyncio.sleep(0.01)
    partial.write_bytes(b"x" * 300)
    manager._append_log("Downloading: docs/archive.bin ... 10%")

    progress = manager.status()["progress"]
    assert progress["activeDownload"] == "docs/archive.bin"  # type: ignore[index]
    assert progress["downloadBytes"] == 300  # type: ignore[index]
    assert progress["downloadSpeed"] > 0  # type: ignore[index]


@pytest.mark.asyncio
async def test_sync_authorization_details_are_exposed(tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")
    manager.mode = "reauth"

    manager._append_log("Open https://login.microsoft.com/device, then continue.")
    manager._append_log("Enter the following code when prompted: ABCD-EFGH")

    authorization = manager.status()["authorization"]
    assert authorization["state"] == "pending"  # type: ignore[index]
    assert authorization["verificationUri"] == "https://login.microsoft.com/device"  # type: ignore[index]
    assert authorization["userCode"] == "ABCD-EFGH"  # type: ignore[index]

    manager._append_log("Access token acquired!")
    assert manager.status()["authorization"]["state"] == "authorized"  # type: ignore[index]
    assert manager.mode == "monitor"


@pytest.mark.asyncio
async def test_reauth_starts_monitor_after_device_authorization(monkeypatch, tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")
    command = []

    class Process:
        returncode = None

    async def create_process(*args, **kwargs):
        command.extend(args)
        return Process()

    async def consume_output(process):
        return None

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(manager, "_consume_output", consume_output)

    await manager.reauth()
    await manager._reader

    assert "--reauth" in command
    assert "--monitor" in command
    assert manager.status()["authorization"]["state"] == "starting"  # type: ignore[index]


@pytest.mark.asyncio
async def test_reauth_process_exit_is_reported_as_failed(tmp_path) -> None:
    manager = SyncManager(tmp_path / "config", tmp_path / "data")
    manager.mode = "reauth"
    manager.authorization_state = "pending"

    class Output:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Process:
        stdout = Output()

        async def wait(self):
            return 1

    process = Process()
    manager.process = process  # type: ignore[assignment]
    await manager._consume_output(process)  # type: ignore[arg-type]

    authorization = manager.status()["authorization"]
    assert authorization["state"] == "failed"  # type: ignore[index]
    assert "租户" in authorization["message"]  # type: ignore[index]

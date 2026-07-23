from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .client_config import ensure_client_config, scope_is_configured
from .graph import GraphClient, GraphError
from .notifications import NotificationError, NotificationManager
from .selection import SelectionStore
from .settings import Settings
from .storage import read_json
from .sync import SyncManager


class FolderSelection(BaseModel):
    folder_ids: list[str] = Field(min_length=1)


class ConfirmedSelection(FolderSelection):
    confirm: bool


class ConfirmRequest(BaseModel):
    confirm: bool


class NotificationRequest(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    events: dict[str, bool] = Field(default_factory=dict)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    sync = SyncManager(settings.config_dir, settings.data_dir)
    graph = GraphClient(settings.graph_client_id, settings.graph_tenant_id, settings.config_dir / "graph-tokens.json")
    selection = SelectionStore(settings.config_dir / "sync_list")
    notifications = NotificationManager(settings.config_dir / "notifications.json")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        ensure_client_config(settings)
        selection.load()
        runtime_state = read_json(settings.config_dir / "manager-state.json", {})
        if isinstance(runtime_state, dict) and runtime_state.get("monitor_enabled"):
            await sync.start("monitor")
        last_event = 0
        graph_was_connected = False
        async def notification_watch() -> None:
            nonlocal last_event, graph_was_connected
            while True:
                await asyncio.sleep(15)
                config = notifications.public()
                if not config["enabled"]:
                    continue
                events = list(sync.events)
                for event in events[last_event:]:
                    if event.get("status") in {"failed", "warning"}:
                        await notifications.send("sync_error", "warning" if event.get("status") == "warning" else "error", str(event.get("detail") or event.get("action")), {"path": event.get("path", ""), "action": event.get("action", "")})
                last_event = len(events)
                status = await graph.check_connection(force=True)
                connected = bool(status.get("verified"))
                if graph_was_connected and not connected:
                    await notifications.send("graph_disconnected", "error", str(status.get("message") or "Microsoft Graph 已断开。"))
                graph_was_connected = connected
        watcher = asyncio.create_task(notification_watch())
        yield
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
        await sync.shutdown()

    app = FastAPI(title="OneSync", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    def bad_request(error: Exception) -> HTTPException:
        return HTTPException(status_code=400, detail=str(error))

    def selected_paths(folder_ids: list[str]) -> list[str]:
        paths: list[str] = []
        for folder_id in folder_ids:
            path = graph.folder_cache.get(folder_id)
            if not path:
                raise HTTPException(status_code=422, detail="Folder selection is stale. Reload the OneDrive folder tree.")
            paths.append(path)
        return paths

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(
            Path(__file__).parent / "static" / "index.html",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        graph_status = await graph.check_connection()
        account = await graph.profile() if graph_status.get("verified") else {}
        return {
            "ok": True,
            "version": os.environ.get("ONESYNC_VERSION", "dev"),
            "dataDirectoryAvailable": settings.data_dir.is_dir(),
            "graphClientConfigured": bool(settings.graph_client_id),
            "sync": sync.status(),
            "graph": graph_status,
            "account": account,
            "scopeConfigured": scope_is_configured(settings, selection),
        }

    @app.get("/api/logs")
    async def logs() -> dict[str, list[str]]:
        return {"lines": list(sync.logs)}

    @app.get("/api/notifications")
    async def notification_settings() -> dict[str, object]:
        return notifications.public()

    @app.put("/api/notifications")
    async def save_notification_settings(request: NotificationRequest) -> dict[str, object]:
        try:
            return notifications.save(request.enabled, request.webhook_url, request.events)
        except NotificationError as error:
            raise bad_request(error)

    @app.post("/api/notifications/test")
    async def test_notifications() -> dict[str, str]:
        try:
            await notifications.send_test()
        except NotificationError as error:
            raise bad_request(error)
        return {"status": "sent"}

    @app.get("/api/selection")
    async def get_selection() -> dict[str, object]:
        return {"folders": selection.load(), "revision": selection.revision}

    @app.post("/api/selection/preview")
    async def preview_selection(request: FolderSelection) -> dict[str, object]:
        paths = selected_paths(request.folder_ids)
        try:
            from .selection import normalize_paths
            normal = normalize_paths(paths)
        except ValueError as error:
            raise bad_request(error)
        return {"folders": normal, "current": selection.load(), "requiresConfirmation": True}

    @app.post("/api/selection/apply")
    async def apply_selection(request: ConfirmedSelection) -> dict[str, object]:
        if not request.confirm:
            raise HTTPException(status_code=422, detail="Folder changes require explicit confirmation.")
        # A running client can resume transfers from its prior scope. Stop it before
        # replacing sync_list so the next resync is the first process to use it.
        await sync.cancel_and_stop()
        write_json_private(settings.config_dir / "manager-state.json", {"monitor_enabled": False})
        try:
            folders = selection.save(selected_paths(request.folder_ids))
        except ValueError as error:
            raise bad_request(error)
        return {"folders": folders, "revision": selection.revision, "resyncRequired": True}

    @app.post("/api/sync/start")
    async def start_sync() -> dict[str, object]:
        if not scope_is_configured(settings, selection):
            raise HTTPException(status_code=422, detail="Sync scope is not configured. Save at least one folder and retry.")
        await sync.start("monitor")
        write_json_private(settings.config_dir / "manager-state.json", {"monitor_enabled": True})
        return sync.status()

    @app.post("/api/sync/once")
    async def sync_once() -> dict[str, object]:
        if not scope_is_configured(settings, selection):
            raise HTTPException(status_code=422, detail="Sync scope is not configured. Save at least one folder and retry.")
        await sync.stop()
        await sync.start("once")
        return sync.status()

    @app.post("/api/sync/stop")
    async def stop_sync() -> dict[str, object]:
        await sync.cancel_and_stop()
        write_json_private(settings.config_dir / "manager-state.json", {"monitor_enabled": False})
        return sync.status()

    @app.post("/api/sync/reauth")
    async def reauth() -> dict[str, object]:
        await sync.reauth()
        return sync.status()

    @app.post("/api/sync/resync", status_code=202)
    async def resync(request: ConfirmRequest) -> dict[str, object]:
        if not request.confirm:
            raise HTTPException(status_code=422, detail="Resync requires explicit confirmation.")
        if not selection.load():
            raise HTTPException(status_code=422, detail="Choose at least one folder before resyncing.")
        if not scope_is_configured(settings, selection):
            raise HTTPException(status_code=422, detail="The OneDrive sync-list configuration is invalid. Restart the manager and retry.")
        if not sync.schedule_resync():
            raise HTTPException(status_code=409, detail="A resync is already running.")
        write_json_private(settings.config_dir / "manager-state.json", {"monitor_enabled": False})
        return {"state": "queued", "operation": sync.status()["operation"]}

    @app.get("/api/graph/auth/status")
    async def graph_status() -> dict[str, object]:
        return graph.auth_status()

    @app.get("/api/graph/status")
    async def graph_status_compat() -> dict[str, object]:
        """Compatibility endpoint for pages cached before the Graph API rename."""
        return graph.auth_status()

    @app.get("/api/graph/auth/check")
    async def graph_check(force: bool = False) -> dict[str, object]:
        return await graph.check_connection(force=force)

    @app.post("/api/graph/auth/device-code")
    async def graph_device_code() -> dict[str, object]:
        try:
            return await graph.begin_device_code()
        except GraphError as error:
            raise bad_request(error)

    @app.post("/api/graph/auth/poll")
    async def graph_poll() -> dict[str, str]:
        try:
            return await graph.poll_device_code()
        except GraphError as error:
            raise bad_request(error)

    @app.get("/api/folders")
    async def folders(parent_id: str = "root", cursor: str | None = None) -> dict[str, object]:
        try:
            return await graph.folders(parent_id, cursor)
        except GraphError as error:
            raise bad_request(error)

    return app


app = create_app()

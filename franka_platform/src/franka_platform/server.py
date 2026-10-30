import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal
import uuid

from websockets.asyncio.server import serve
from .config import load, with_permission
from .core import Platform
from .protocol import PlatformError, dumps, fields, identifier, loads, require


def logger(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("franka_platform.audit."+str(path))
    log.setLevel(logging.INFO)
    log.propagate = False
    if not log.handlers:
        log.addHandler(RotatingFileHandler(path, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8"))
    return lambda event: log.info(dumps(event))


def dispatch(platform, connection, raw):
    fields(raw, ("schema_version", "rpc_id", "method", "params"), "RPC")
    require(type(raw["schema_version"]) is int and raw["schema_version"] == 1, "INVALID_ACTION", "Unsupported schema version")
    identifier(raw["rpc_id"], "rpc_id")
    method, params = raw["method"], raw["params"]
    require(isinstance(method, str) and isinstance(params, dict), "INVALID_ACTION", "Invalid method or params")
    reads = {"get_capabilities": platform.capabilities, "get_status": platform.status,
             "get_observation": platform.observation}
    if method in reads:
        fields(params, (), "params")
        return reads[method]()
    if method == "get_command_status":
        fields(params, ("request_id",), "params")
        identifier(params["request_id"], "request_id")
        return platform.command_status(params["request_id"])
    if method == "acquire_control":
        fields(params, (), "params")
        return platform.acquire(connection)
    if method == "send_action":
        fields(params, ("action",), "params")
        return platform.send_action(connection, params["action"])
    writes = {"heartbeat": platform.heartbeat, "stop": platform.stop, "release_control": platform.release}
    if method in writes:
        fields(params, ("session_id",), "params")
        return writes[method](connection, params["session_id"])
    if method == "set_control_mode":
        fields(params, ("session_id", "mode"), "params")
        return platform.set_mode(connection, params["session_id"], params["mode"])
    raise PlatformError("UNSUPPORTED_METHOD", "Unknown RPC method")


class Service:
    def __init__(self, platform):
        self.platform = platform
        self.server = self.task = None

    async def handler(self, socket):
        cid = uuid.uuid4().hex
        try:
            async for data in socket:
                raw = None
                try:
                    raw = loads(data)
                    # Expiry is checked at dispatch as well as by the independent task.
                    self.platform.tick()
                    result = dispatch(self.platform, cid, raw)
                    response = {"schema_version": 1, "rpc_id": raw["rpc_id"], "ok": True, "result": result}
                except PlatformError as exc:
                    rid = raw.get("rpc_id") if isinstance(raw, dict) else None
                    response = {"schema_version": 1, "rpc_id": rid, "ok": False, "error": exc.as_dict()}
                    action = raw.get("params", {}).get("action") if isinstance(raw, dict) and isinstance(raw.get("params"), dict) else None
                    self.platform._log("rpc_rejected", rpc_id=rid, raw_request=action, error=exc.as_dict())
                except Exception:
                    self.platform.disconnect(cid)
                    response = {"schema_version": 1, "rpc_id": None, "ok": False,
                                "error": {"code": "INTERNAL_ERROR", "message": "Connection invalidated"}}
                await asyncio.wait_for(socket.send(dumps(response)), timeout=2)
        finally:
            self.platform.disconnect(cid)

    async def watchdog(self):
        while True:
            await asyncio.sleep(self.platform.cfg["timing"]["watchdog_period_s"])
            self.platform.tick()

    async def start(self):
        n = self.platform.cfg["network"]
        self.server = await serve(self.handler, n["host"], n["port"], max_size=512*1024,
                                  max_queue=4, origins=[None], compression=None,
                                  ping_interval=1, ping_timeout=2, close_timeout=1)
        self.task = asyncio.create_task(self.watchdog())
        return self.server.sockets[0].getsockname()[1]

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.platform.close()


async def run(cfg):
    if cfg["backend"] == "mock":
        from .backends.mock import MockBackend
        backend = MockBackend(cfg)
    else:
        from .backends.ros2 import ROS2Backend
        backend = ROS2Backend(cfg)
    service = Service(Platform(cfg, backend, log=logger(cfg["log_path"])))
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, done.set)
    try:
        port = await service.start()
        print(dumps({"event": "PLATFORM_READY", "schema_version": 1, "host": cfg["network"]["host"],
                     "port": port, "backend": cfg["backend"], "permission": cfg["permission"]}), flush=True)
        await done.wait()
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--permission", choices=("read_only", "dry_run", "execute"))
    args = parser.parse_args()
    try:
        cfg = load(args.config)
        if args.permission:
            cfg = with_permission(cfg, args.permission)
        asyncio.run(run(cfg))
    except PlatformError as exc:
        parser.exit(2, dumps({"error": exc.as_dict()})+"\n")


if __name__ == "__main__":
    main()

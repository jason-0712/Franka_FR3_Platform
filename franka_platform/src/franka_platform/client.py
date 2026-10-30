"""Async SDK: loopback and SSH-forwarded remote connections use identical RPCs."""
import asyncio
import contextlib
import uuid
from websockets.asyncio.client import connect
from .protocol import PlatformError, dumps, loads, require


class Client:
    def __init__(self, url="ws://127.0.0.1:8765", timeout_s=5):
        self.url, self.timeout_s = url, timeout_s
        self.socket = self.session_id = self.control_epoch = self._heartbeat_task = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self.socket = await connect(self.url, proxy=None, max_size=16*1024*1024, compression=None, close_timeout=1)
        return await self.get_capabilities()

    async def _rpc(self, method, **params):
        require(self.socket is not None, "NOT_CONNECTED", "Call connect first")
        rid = uuid.uuid4().hex
        async with self._lock:
            try:
                async with asyncio.timeout(self.timeout_s) if hasattr(asyncio, "timeout") else _Timeout(self.timeout_s):
                    await self.socket.send(dumps({"schema_version": 1, "rpc_id": rid, "method": method, "params": params}))
                    response = loads(await self.socket.recv())
            except BaseException:
                # A timed out reply cannot be mistaken for the next RPC. No automatic retries.
                await self.socket.close()
                self.session_id = self.control_epoch = None
                raise
        require(response.get("schema_version") == 1 and response.get("rpc_id") == rid,
                "PROTOCOL_ERROR", "Response correlation mismatch")
        if not response["ok"]:
            raise PlatformError(response["error"]["code"], response["error"]["message"])
        return response["result"]

    async def get_capabilities(self):
        return await self._rpc("get_capabilities")

    async def get_status(self):
        return await self._rpc("get_status")

    async def get_observation(self):
        return await self._rpc("get_observation")

    async def get_command_status(self, request_id):
        return await self._rpc("get_command_status", request_id=request_id)

    async def acquire_control(self):
        result = await self._rpc("acquire_control")
        self.session_id, self.control_epoch = result["session_id"], result["control_epoch"]
        self._heartbeat_task = asyncio.create_task(self._heartbeat(result["lease_timeout_s"]/3))
        return result

    async def _heartbeat(self, interval):
        try:
            while self.session_id:
                await asyncio.sleep(interval)
                await self._rpc("heartbeat", session_id=self.session_id)
        except Exception:
            self.session_id = self.control_epoch = None

    async def set_control_mode(self, mode):
        result = await self._rpc("set_control_mode", session_id=self.session_id, mode=mode)
        self.control_epoch = result["control_epoch"]
        return result

    def action(self, action_type, payload, observation, request_id=None):
        return {"schema_version": 1, "request_id": request_id or uuid.uuid4().hex,
                "session_id": self.session_id, "control_epoch": self.control_epoch,
                "observation_id": observation["observation_id"], "type": action_type, "payload": payload}

    async def send_action(self, action):
        return await self._rpc("send_action", action=action)

    async def set_gripper(self, width_m, observation=None, request_id=None):
        observation = observation or await self.get_observation()
        return await self.send_action(self.action("gripper_width", {"width_m": width_m}, observation, request_id))

    async def stop(self):
        result = await self._rpc("stop", session_id=self.session_id)
        self.control_epoch = result["control_epoch"]
        return result

    async def _cancel_heartbeat(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

    async def release_control(self):
        await self._cancel_heartbeat()
        result = await self._rpc("release_control", session_id=self.session_id)
        self.session_id = self.control_epoch = None
        return result

    async def close(self):
        await self._cancel_heartbeat()
        if self.socket:
            await self.socket.close()
            self.socket = None
        self.session_id = self.control_epoch = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()


class _Timeout:
    """Python 3.10 equivalent of asyncio.timeout, without another dependency."""
    def __init__(self, seconds):
        self.seconds = seconds

    async def __aenter__(self):
        self.task = asyncio.current_task()
        self.expired = False
        def cancel():
            self.expired = True
            self.task.cancel()
        self.timer = asyncio.get_running_loop().call_later(self.seconds, cancel)

    async def __aexit__(self, typ, value, tb):
        self.timer.cancel()
        if typ is asyncio.CancelledError and self.expired:
            raise asyncio.TimeoutError from value

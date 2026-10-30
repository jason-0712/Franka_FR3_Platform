"""RPC liveness only; does not certify sensor, FCI, or controller health."""
import asyncio
import os
import yaml
from franka_platform.client import Client


async def main():
    with open(os.environ['FRANKA_PLATFORM_CONFIG'], encoding='utf-8') as stream:
        network = yaml.safe_load(stream)['network']
    url = os.environ.get('FRANKA_PLATFORM_HEALTH_URL', 'ws://127.0.0.1:'+str(network['port']))
    async with Client(url) as client:
        await client.get_status()


asyncio.run(main())

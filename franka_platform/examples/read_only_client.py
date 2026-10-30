"""Read observations; save actual transmitted images only when requested."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
from franka_platform.client import Client


async def run(args):
    async with Client(args.url) as client:
        print(json.dumps(await client.get_capabilities(), ensure_ascii=False))
        obs = await client.get_observation()
        if args.output:
            directory = Path(args.output)
            directory.mkdir(parents=True, exist_ok=True)
            for c in obs["cameras"]:
                if c["available"]:
                    (directory/(c["name"]+"."+c["encoding"])).write_bytes(base64.b64decode(c["data_base64"], validate=True))
            (directory/"observation.json").write_text(json.dumps(obs, ensure_ascii=False, indent=2))
        summary = {**obs, "cameras": [{k: v for k, v in c.items() if k != "data_base64"} for c in obs["cameras"]]}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(await client.get_status(), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--output")
    asyncio.run(run(parser.parse_args()))

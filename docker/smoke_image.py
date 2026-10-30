"""Test a built image in disposable containers; real mode is subscription-only."""
import argparse
import asyncio
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
import yaml

from franka_platform.client import Client
from franka_platform.protocol import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def command(args, timeout=120):
    p = subprocess.run([str(a) for a in args], text=True, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr[-3000:] or p.stdout[-3000:])
    return p.stdout


async def reader(url):
    deadline = time.monotonic()+15
    async with Client(url) as client:
        while True:
            obs = await client.get_observation()
            if obs['freshness']['action_blocker'] is None:
                break
            assert time.monotonic() < deadline, obs['freshness']
            await asyncio.sleep(.2)
        cap = await client.get_capabilities()
        assert cap['permission'] == 'read_only'
        try:
            await client.acquire_control()
        except PlatformError as exc:
            assert exc.code == 'READ_ONLY', exc.code
        else:
            raise AssertionError('Reader unexpectedly acquired control')
        images = []
        for cam in obs['cameras']:
            data = base64.b64decode(cam['data_base64'], validate=True)
            assert data and cam['available']
            images.append({k:cam[k] for k in ('name','source','encoding','width','height','age_s')})
            images[-1]['received_bytes'] = len(data)
        status = await client.get_status()
        assert status['actuator_write_count'] == 0
        return {'status':'PASS','backend':cap['backend'],'permission':cap['permission'],
                'acquire_error':'READ_ONLY','actuator_writes':0,'freshness':obs['freshness'],'cameras':images}


def test_container(image, config, directory, robot_description=None, actions=False):
    config = copy.deepcopy(config)
    config['network'] = {'host':'127.0.0.1','port':0}
    config['log_path'] = '/tmp/franka-platform-smoke.jsonl'
    if robot_description:
        config['ros']['robot_description_file'] = '/run/franka/robot.urdf'
    path = directory/'config.yaml'
    path.write_text(yaml.safe_dump(config))
    path.chmod(0o644)
    name = 'franka-fr3-smoke-'+uuid.uuid4().hex[:10]
    cmd = ['docker','run','-d','--rm','--init','--network','host','--read-only',
           '--tmpfs','/tmp','--cap-drop','ALL','--security-opt','no-new-privileges',
           '--no-healthcheck','--name',name,'--mount',f'type=bind,source={path},target=/run/franka/config.yaml,readonly',
           '-e','FRANKA_PLATFORM_CONFIG=/run/franka/config.yaml',
           '-e','ROS_DOMAIN_ID='+str(config['ros']['domain_id']),
           '-e','RMW_IMPLEMENTATION='+config['ros']['middleware']]
    if robot_description:
        cmd += ['--mount',f'type=bind,source={robot_description},target=/run/franka/robot.urdf,readonly']
    command([*cmd,image])
    try:
        deadline = time.monotonic()+20
        ready = None
        while ready is None:
            logs = command(['docker','logs',name])
            for line in logs.splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get('event') == 'PLATFORM_READY':
                    ready = record
            if ready is None:
                assert time.monotonic() < deadline, logs[-2000:]
                time.sleep(.2)
        url = 'ws://127.0.0.1:'+str(ready['port'])
        if actions:
            assert config['backend'] == 'mock'
            output = command([sys.executable,ROOT/'franka_platform/examples/mock_actions.py','--url',url])
            assert 'MOCK_EXAMPLE=PASS' in output
            async def status():
                async with Client(url) as client:
                    return await client.get_status()
            detail = asyncio.run(status())
            if config['permission'] == 'dry_run':
                assert detail['actuator_write_count'] == 0
            result = {'status':'PASS','backend':'mock','permission':config['permission'],
                      'three_actions_and_gripper':'PASS','actuator_writes':detail['actuator_write_count']}
        else:
            result = asyncio.run(reader(url))
        if config['backend'] == 'real':
            detail = json.loads(command(['docker','exec',name,'/usr/local/bin/franka-platform-entrypoint','python',
                '/opt/franka-platform/scripts/franka_platform/inspect_ros_readonly.py',
                '--config','/run/franka/config.yaml','--output','/tmp/readonly','--duration-s','1']))
            assert detail['status'] == 'PASS' and detail['actuator_write_count'] == 0
            assert all(topic == '/parameter_events' for topic,types in detail['own_publishers'])
            result['own_publishers'] = detail['own_publishers']
        return result
    finally:
        subprocess.run(['docker','stop','--time','5',name], capture_output=True)
        subprocess.run(['docker','rm','-f',name], capture_output=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='jiahanyu/franka_fr3:0.1.0-preview')
    parser.add_argument('--real-config')
    parser.add_argument('--robot-description')
    parser.add_argument('--output', default='artifacts/franka_platform/docker/smoke.json')
    args = parser.parse_args()
    checks = {}
    output = command(['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp',
                      '--cap-drop','ALL','--security-opt','no-new-privileges',args.image,
                      'bash','-c','set -e; /usr/local/bin/franka-platform-entrypoint self-test >&2; '
                      'cat /tmp/franka-platform-acceptance.json'])
    acceptance = json.loads(output)
    assert acceptance['status'] == 'PASS'
    assert not any(acceptance['model_packages_present'].values())
    checks['isolated_self_test'] = {'status':'PASS','network':'none',
                                  'tests_passed':acceptance['tests_run']-len(acceptance['skipped']),
                                  'skipped':acceptance['skipped'],
                                  'model_packages_present':acceptance['model_packages_present']}
    output = command(['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp',
                      '--cap-drop','ALL','--security-opt','no-new-privileges',args.image,'python','-c',
                      'import ctypes,json; from pathlib import Path; '
                      'm=json.loads(Path("/opt/franka-image-manifest/native-build.json").read_text()); '
                      'libs=m["libraries_sha256"]; '
                      '[ctypes.CDLL(str(Path("/opt/franka-control")/p)) for p in libs]; '
                      'print(json.dumps({"status":"PASS","network":"none",'
                      '"libraries_loaded":len(libs),"packages":m["packages"]}))'])
    checks['native_library_loading'] = json.loads(output)
    with tempfile.TemporaryDirectory(prefix='franka-fr3-image-') as temporary:
        directory = Path(temporary)
        directory.chmod(0o755)
        mock = yaml.safe_load((ROOT/'franka_platform/configs/mock.yaml').read_text())
        checks['mock_read_only'] = test_container(args.image,mock,directory)
        for mode in ('execute','dry_run'):
            mock['permission'] = mode
            checks['mock_'+mode] = test_container(args.image,mock,directory,actions=True)
        if args.real_config:
            assert args.robot_description, '--robot-description is required for a real reader'
            real = yaml.safe_load(Path(args.real_config).read_text())
            assert real['backend'] == 'real' and real['permission'] == 'read_only'
            checks['real_read_only'] = test_container(args.image,real,directory,
                                                     Path(args.robot_description).resolve())
        else:
            checks['real_read_only'] = {'status':'NOT_RUN','reason':'no field configuration selected'}
    report = {'schema_version':1,'image':args.image,'status':'PASS','checks':checks,
              'hardware_execution':'NOT_RUN','second_computer_migration':'NOT_RUN'}
    out = Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()

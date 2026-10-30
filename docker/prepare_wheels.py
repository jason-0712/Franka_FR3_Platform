"""Fetch SHA256-locked public wheels for offline Python 3.10 image installation."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
lock = json.loads((ROOT/'docker/python-wheels.lock.json').read_text())
destination = ROOT/'artifacts/franka_platform/docker/wheels'
destination.mkdir(parents=True, exist_ok=True)
expected = set()
for wheel in lock['wheels']:
    name = wheel['filename']
    assert Path(name).name == name and name.endswith('.whl')
    url = urlsplit(wheel['url'])
    assert url.scheme == 'https' and url.hostname == 'files.pythonhosted.org'
    expected.add(name)
    path = destination/name
    if not path.exists():
        with urlopen(wheel['url'], timeout=60) as response:
            content = response.read()
        assert hashlib.sha256(content).hexdigest() == wheel['sha256'], 'Download SHA256 mismatch: '+name
        path.write_bytes(content)
    assert path.stat().st_size == wheel['size']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == wheel['sha256'], 'Cached SHA256 mismatch: '+name
assert {p.name for p in destination.glob('*.whl')} == expected, 'Unexpected wheel in build inputs'
print(json.dumps({'status':'PASS','verified_wheels':len(expected),'python':lock['python']}))

"""Validate native input sources before a local Docker build; no hardware access."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


baseline = json.loads((ROOT/'SOURCE_BASELINE.json').read_text())
for name, digest in baseline['vendored_files_sha256'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, 'Vendor source changed: '+name
for dep in [*baseline['submodules'], baseline['nested_libfranka_common']]:
    checkout = ROOT/dep['path']
    assert (checkout/'.git').exists(), 'Missing recursive submodule: '+dep['path']
    assert git('rev-parse', 'HEAD', cwd=checkout) == dep['commit'], 'Unexpected commit: '+dep['path']
    assert not git('ls-files', '--others', '--exclude-standard', cwd=checkout), \
        'Untracked native source files: '+dep['path']
    expected = ''
    patch = ROOT/'patches/nested_repos'/(dep['path'].replace('/', '__')+'.patch')
    if patch.exists():
        expected = patch.read_text().strip()
        assert hashlib.sha256(patch.read_bytes()).hexdigest() == baseline['patches_sha256'][str(patch.relative_to(ROOT))]
    actual = git('diff', 'HEAD', '--binary', '--ignore-submodules=all', cwd=checkout)
    assert actual == expected, 'Unexpected native changes or unapplied patch: '+dep['path']
print(json.dumps({'status': 'PASS', 'vendor_files': len(baseline['vendored_files_sha256']),
                  'recursive_dependencies': len(baseline['submodules'])+1, 'hardware_connections': 0}))

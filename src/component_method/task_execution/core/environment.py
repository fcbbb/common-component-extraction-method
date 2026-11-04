"""Preserve official dependencies, prove offline inference, validate patches."""
import base64
import io
import json
import re
import shlex
import subprocess
import tarfile
from pathlib import Path

import docker
from common import OUT, task_data_root, write, now, rows

COMPONENT_PYTHONPATH = '/testbed:/testbed/component_bundle'


def image_for(task):
    return task['image_name']


def prepare_runtime(task):
    client = docker.from_env()
    try: image = client.images.get(task['image_name'])
    except docker.errors.ImageNotFound:
        subprocess.run(['docker', 'pull', task['image_name']], check=True)
        image = client.images.get(task['image_name'])
    return task['image_name'], image.id


def initialize_task(container, task):
    # Only the disposable task container is changed, never the image or dependencies.
    name = task['repo'].split('/')[1]
    code = """import os,shutil,sys
name=sys.argv[1]
source='/'+name
os.makedirs('/testbed',exist_ok=True)
for entry in os.scandir(source):
    shutil.move(entry.path, '/testbed/'+entry.name)
os.rmdir(source)
os.symlink('/testbed',source)
shutil.rmtree('/root/my_repo',ignore_errors=True)
shutil.rmtree('/root/.cache/pip',ignore_errors=True)
os.makedirs('/testbed/component_bundle',exist_ok=True)
with open('/testbed/.git/info/exclude','a') as f:f.write('\\ncomponent_bundle/\\n')
"""
    result = container.exec_run(['python', '-c', code, name], workdir='/')
    if result.exit_code: raise RuntimeError(result.output.decode(errors='replace'))


def network_probe(container):
    container.reload()
    if container.attrs['HostConfig']['NetworkMode'] != 'none':
        raise RuntimeError('Task container is not offline')
    if container.attrs['HostConfig'].get('Privileged'):
        raise RuntimeError('Privileged task container is forbidden')
    if any(m.get('Destination') == '/var/run/docker.sock' for m in container.attrs.get('Mounts', [])):
        raise RuntimeError('Docker socket must not be exposed')
    code = '''import socket,json
results={}
for host,port in [('1.1.1.1',443),('raw.githubusercontent.com',443)]:
 try:
  s=socket.create_connection((host,port),timeout=1);s.close();results[host]=False
 except OSError:results[host]=True
print(json.dumps(results))
assert all(results.values())
'''
    result = container.exec_run(['python', '-c', code])
    if result.exit_code: raise RuntimeError('Actual outbound connection probe failed: ' + result.output.decode(errors='replace'))
    return {'network_mode': 'none', 'outbound_connections_blocked': json.loads(result.output.decode()),
            'image_id': container.attrs['Image'], 'checked_at': now()}


def preflight(task, image):
    task = next(t for t in rows() if t['image_name'] == image)
    client = docker.from_env(); container = client.containers.run(
        image, ['sleep', '600'], detach=True, network_mode='none', cap_drop=['ALL'],
        security_opt=['no-new-privileges:true'], entrypoint=[], pids_limit=128)
    try:
        result = network_probe(container)
        repo_path = '/' + task['repo'].split('/')[1]
        probe = container.exec_run(['git', '-C', repo_path, 'rev-parse', 'HEAD'])
        assert probe.exit_code == 0
        actual = probe.output.decode().strip()
        assert actual == task['base_commit'], (task['instance_id'], actual, task['base_commit'])
        history_probe = container.exec_run(['/bin/bash', '-c',
            'git rev-list --all --not HEAD | wc -l; git reflog --all --format=%H | wc -l; git fsck --no-reflogs --unreachable 2>/dev/null | wc -l'], workdir=repo_path)
        assert history_probe.exit_code == 0
        counts = [int(v) for v in history_probe.output.decode().splitlines()]
        assert counts == [0, 0, 0], ('Unexamined future/reflog/unreachable history in official image', task['instance_id'], counts)
        result['git_history_exposure'] = {'nonancestor_commits': counts[0], 'reflog_entries': counts[1], 'unreachable_objects': counts[2]}

        package = {'pyjanitor-devs/pyjanitor': 'janitor', 'apiflask/apiflask': 'apiflask',
                   'wtforms/wtforms': 'wtforms', 'jelmer/dulwich': 'dulwich', 'elastic/curator': 'curator', 'yukinarit/pyserde': 'serde',
                   'pytask-dev/pytask': 'pytask', 'rochacbruno/dynaconf': 'dynaconf',
                   'ericmjl/pyjanitor': 'janitor', 'pydicom/pydicom': 'pydicom',
                   'rock-learning/pytransform3d': 'pytransform3d', 'python-babel/babel': 'babel',
                   'pennylaneai/pennylane': 'pennylane',
                   'qiskit-community/ffsim': 'ffsim', 'niconoe/pyinaturalist': 'pyinaturalist',
                   'tefra/xsdata': 'xsdata', 'samuelcolvin/pydantic': 'pydantic',
                   'fatiando/harmonica': 'harmonica',
                   'pybamm-team/pybamm': 'pybamm', 'mpmath/mpmath': 'mpmath', 'stingraysoftware/stingray': 'stingray'}[task['repo'].lower()]
        code = f'import {package},json,sys; print(json.dumps({{"python":sys.version,"package_file":{package}.__file__}}))'
        imported = container.exec_run(['python', '-c', code], workdir=repo_path)
        assert imported.exit_code == 0, imported.output.decode(errors='replace')
        result.update(base_commit=actual, runtime=json.loads(imported.output.decode().splitlines()[-1]))
        assert result['runtime']['package_file'].startswith(('/testbed/', '/' + task['repo'].split('/')[1] + '/'))
        # Host-only copies are for cross-baseline smoke, never for task agents.
        baseline = task_data_root() / 'source_snapshot'
        if not baseline.exists():
            stage = baseline.parent / (baseline.name + '-unpack'); stage.mkdir(parents=True, exist_ok=True)
            stream, _ = container.get_archive(repo_path)
            archive = stage / 'source.tar'
            with archive.open('wb') as handle:
                for chunk in stream: handle.write(chunk)
            def source_filter(member, destination):
                if '.venv' in Path(member.name).parts:
                    return None
                return tarfile.data_filter(member, destination)
            with tarfile.open(archive, 'r') as tar:
                tar.extractall(stage, filter=source_filter)
            (stage / task['repo'].split('/')[1]).rename(baseline)
            archive.unlink(); stage.rmdir()
            import shutil
            shutil.rmtree(baseline / '.git', ignore_errors=True)
            for generated in list(baseline.rglob('__pycache__')):
                shutil.rmtree(generated, ignore_errors=True)
            for link in list(baseline.rglob('*')):
                if link.is_symlink() and link.resolve().is_relative_to(baseline.resolve()) and link.resolve().is_file():
                    content = link.resolve().read_bytes(); link.unlink(); link.write_bytes(content)
        write(OUT / 'runtime/proofs' / (task['instance_id'] + '.json'), result)
        return result
    finally: container.remove(force=True)


def collect_patch(environment, base_commit, allow_empty=False):
    assert re.fullmatch(r'[0-9a-f]{40}', base_commit)
    # DockerEnvironment.execute uses text=True. Send ASCII across that boundary
    # so universal-newline decoding cannot destroy CR bytes in Git context.
    script = (
        'import base64,subprocess; '
        'subprocess.check_call(["git","add","-A"]); '
        f'patch=subprocess.check_output(["git","-c","core.pager=cat","diff",'
        f'"--cached","--binary","--no-ext-diff","--unified=3","{base_commit}"]); '
        'print("PATCH_BASE64="+base64.b64encode(patch).decode("ascii"))'
    )
    result = environment.execute('python -c ' + shlex.quote(script), cwd='/testbed', timeout=120)
    if result['returncode'] != 0:
        raise ValueError('Could not collect repository diff')
    payloads = [line[len('PATCH_BASE64='):] for line in result['output'].splitlines()
                if line.startswith('PATCH_BASE64=')]
    if len(payloads) != 1:
        raise ValueError('Missing or ambiguous byte-safe patch payload')
    patch = base64.b64decode(payloads[0], validate=True).decode('utf-8')
    if allow_empty and not patch.strip():
        return ''
    if not patch.lstrip().startswith('diff --git '):
        raise ValueError('Submission has no complete Git patch')
    return patch



def check_patch(image, patch):
    task = next(t for t in rows() if t['image_name'] == image)
    client = docker.from_env(); container = client.containers.run(
        image, ['sleep', '60'], detach=True, network_mode='none', cap_drop=['ALL'],
        security_opt=['no-new-privileges:true'], entrypoint=[])
    try:
        content = patch.encode(); archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            item = tarfile.TarInfo('agent.patch'); item.size = len(content); tar.addfile(item, io.BytesIO(content))
        container.put_archive('/tmp', archive.getvalue())
        result = container.exec_run(['git', 'apply', '--check', '/tmp/agent.patch'], workdir='/' + task['repo'].split('/')[1])
        if result.exit_code: raise ValueError('Patch cannot apply to clean official baseline: ' + result.output.decode(errors='replace'))
    finally: container.remove(force=True)


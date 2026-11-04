"""Original official images, patches, test commands and parser; no services."""
import importlib.util
import hashlib
from pathlib import Path
import shlex
import subprocess
import tempfile
import uuid

import docker
from common import OUT, RUNTIME_ROOT, evaluation_adjustments, write


EVALUATOR_SHA256 = "4768c0c3e2adf3540c2228f819f4b073e4665ada06fa00f2234a1f7620d69eda"


def evaluator():
    path = RUNTIME_ROOT / 'vendor/official_eval'
    evaluator_path = path / 'scripts/eval.py'
    assert hashlib.sha256(evaluator_path.read_bytes()).hexdigest() == EVALUATOR_SHA256, 'Official evaluator was modified'
    spec = importlib.util.spec_from_file_location('official_rebench_eval', evaluator_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def not_evaluated(task, output, reason):
    result = {'instance_id': task['instance_id'], 'evaluated': False, 'error': reason,
              'passed_match': False, 'required_tests_passed': False}
    write(Path(output) / 'result.json', result)
    return result


def evaluate(task, patch, output, bundle=None):
    helper = evaluator(); output = Path(output); output.mkdir(parents=True, exist_ok=True)
    adjustment = evaluation_adjustments().get(task['instance_id'], {})
    excluded = adjustment.get('excluded_tests', [])
    # Never substitute a task runtime or a component-baked image for this image.
    image = docker.from_env().images.get(task['image_name']).id
    if (OUT / 'prepared.json').exists():
        assert image == read(OUT / 'prepared.json')['official_images'][task['instance_id']]
    workdir = '/' + task['repo'].split('/')[1]
    name = 'minimal-eval-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='minimal-eval-') as directory:
        directory = Path(directory)
        directory.chmod(0o755)  # Container root has no DAC override after cap-drop=ALL.
        (directory / 'source.patch').write_text(patch or '')
        (directory / 'test.patch').write_text(task['test_patch'])
        apply = 'git apply -v --3way --recount --ignore-space-change --whitespace=nowarn '
        commands = ['set -e', 'test "$(git rev-parse HEAD)" = ' + shlex.quote(task['base_commit']),
                    'git reset --hard HEAD']
        if patch: commands.append(apply + '/patches/source.patch')
        commands.append(apply + '/patches/test.patch')
        if excluded:
            options = shlex.quote(' '.join('--deselect=' + test for test in excluded))
            commands.append('export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} "' + options)
        commands += helper.normalize_command_list(task['install_config']['test_cmd'], 'test_cmd', task['instance_id'])
        args = ['docker', 'run', '--rm', '--pull=never', '--name', name, '--network=none',
                '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '-v', str(directory) + ':/patches:ro', '-w', workdir]
        if bundle:
            # The executable component artifact is part of the component treatment.
            # Both paths cover relative imports and the task environment's absolute path.
            for destination in (workdir + '/component_bundle', '/testbed/component_bundle'):
                args += ['-v', str(Path(bundle).resolve()) + ':' + destination + ':ro']
        args += ['-e', 'PYTHONPATH=' + workdir + ':' + workdir + '/component_bundle:/testbed:/testbed/component_bundle', image, '/bin/bash', '-c', '\n'.join(commands)]
        error = None
        try:
            with (output / 'tests.log').open('w') as handle:
                code = subprocess.run(args, stdout=handle, stderr=subprocess.STDOUT, timeout=1800).returncode
        except subprocess.TimeoutExpired:
            code, error = 124, 'Evaluation process timed out'
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
    parsed = helper.get_parser(task['install_config']['log_parser'])((output / 'tests.log').read_text())
    parsed = {helper._normalize_test_name(k): v for k, v in parsed.items()}
    passed = sorted(k for k, v in parsed.items() if v == 'PASSED')
    excluded_names = {helper._normalize_test_name(k) for k in excluded}
    f2p = {helper._normalize_test_name(k) for k in task['FAIL_TO_PASS']} - excluded_names
    p2p = {helper._normalize_test_name(k) for k in task['PASS_TO_PASS']} - excluded_names; expected = f2p | p2p
    expected_list = sorted(helper._normalize_test_name(k) for k in task['FAIL_TO_PASS'] + task['PASS_TO_PASS']
                           if helper._normalize_test_name(k) not in excluded_names)
    if not expected.intersection(parsed):
        error = error or 'No registered test outcomes; inspect tests.log for an infrastructure failure.'
    result = {'instance_id': task['instance_id'], 'image': task['image_name'], 'image_id': image,
              'network': 'none', 'evaluated': True, 'exit_code': code, 'error': error,
              'F2P_passed': len(f2p & set(passed)), 'F2P_failed': sum(parsed.get(k) == 'FAILED' for k in f2p),
              'F2P_total': len(f2p), 'P2P_passed': len(p2p & set(passed)), 'P2P_total': len(p2p),
              'missing_required': sorted(expected - set(passed)), 'extra_passed': sorted(set(passed) - expected),
              'passed_match': passed == expected_list, 'required_tests_passed': expected.issubset(passed)}
    if excluded:
        result['evaluation_adjustment'] = adjustment
    write(output / 'result.json', result)
    return result

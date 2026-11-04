"""Same official mini agent loop, with offline checks and actual patch capture."""
import argparse
import hashlib
import json
import os
import signal
import traceback
import time
from pathlib import Path

import docker
import yaml
from minisweagent.agents.default import FormatError, Submitted
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.models import get_model
from minisweagent.run.utils.save import save_traj
from common import OUT, CONFIG, agent_rows, rows, write, model_env, model_config, hashes, digest, now, verify_inputs, settings
from environment import collect_patch, check_patch, network_probe, initialize_task, COMPONENT_PYTHONPATH
from action_protocol import CompatibleActionAgent
from component_usage import collect_component_usage


class TaskEnvironmentLost(RuntimeError):
    pass


class TaskDockerEnvironment(DockerEnvironment):
    def ensure_running(self):
        try:
            container = docker.from_env().containers.get(self.container_id)
        except docker.errors.NotFound as error:
            raise TaskEnvironmentLost('Task container disappeared; stop instead of retrying model actions.') from error
        if container.status != 'running':
            raise TaskEnvironmentLost('Task container is no longer running.')

    def execute(self, command, cwd='', *, timeout=None):
        self.ensure_running()
        result = super().execute(command, cwd, timeout=timeout)
        if result['returncode'] and 'Error response from daemon:' in result['output']:
            self.ensure_running()
        return result


class CapturingAgent(CompatibleActionAgent):
    def query(self):
        if isinstance(self.env, TaskDockerEnvironment):
            self.env.ensure_running()
        response = super().query()
        write(self.output_dir / 'state.json', {'status': 'running', 'model_calls': self.model.n_calls,
              'reported_cost_usd': self.model.cost, 'updated_at': now()})
        save_traj(self, self.output_dir / 'checkpoint.traj.json', exit_status='Running', result='')
        print('Model response', self.model.n_calls, 'reference cost', round(self.model.cost, 6), flush=True)
        return response

    def has_finished(self, output):
        lines = output.get('output', '').lstrip().splitlines()
        if not lines or lines[0].strip() not in ('COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT', 'MINI_SWE_AGENT_FINAL_OUTPUT'):
            return
        if output.get('returncode') != 0:
            raise FormatError('Submission command failed. Correct it and submit the complete patch again.')
        try:
            patch = collect_patch(self.env, self.base_commit)
            check_patch(self.env.config.image, patch)
        except ValueError as error:
            raise FormatError(str(error))
        self.patch = patch
        (self.output_dir / 'submitted.patch').write_text(patch)
        write(self.output_dir / 'patch_capture.json', {'source': 'actual_repository_diff',
              'base_commit': self.base_commit, 'sha256': hashlib.sha256(patch.encode()).hexdigest(),
              'clean_baseline_apply_check': 'passed', 'captured_at': now()})
        raise Submitted(patch)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--task', required=True); parser.add_argument('--arm', choices=['direct', 'components'], required=True)
    parser.add_argument('--image', required=True); parser.add_argument('--bundle', type=Path)
    args = parser.parse_args()
    verify_inputs()
    os.environ.update(model_env())
    out = OUT / 'tasks' / args.arm / args.task; out.mkdir(parents=True, exist_ok=True)
    if (out / 'result.json').exists():
        print('Existing attempt retained', args.task, args.arm); return
    official = next(r for r in rows() if r['instance_id'] == args.task)
    original = next(r for r in agent_rows() if r['instance_id'] == args.task)
    config = yaml.safe_load((CONFIG / 'task.yaml').read_text())
    config['model'] = model_config()
    if args.arm == 'components' and args.bundle:
        from component_method.library_publish.agent_bundle import agent_bundle_prompt
        config['agent']['instance_template'] += '\n\n' + agent_bundle_prompt(CONFIG)
    ec = config['environment'].copy(); ec.pop('environment_class', None); ec['image'] = args.image
    if args.bundle:
        manifest = read(args.bundle / 'manifest.json')
        assert manifest['repository'] == official['repo'].lower()
        binding = read(OUT / 'bindings' / (args.task + '.json'))
        assert binding['base_commit'] == official['base_commit']
        assert binding['bundle_sha256'] == digest(hashes(args.bundle))
        ec['run_args'] += ['--mount', f'type=bind,source={args.bundle.resolve()},target=/testbed/component_bundle,readonly']
        ec['env']['PYTHONPATH'] = COMPONENT_PYTHONPATH
    # Explicitly clear inherited package index/proxy access in the execution shell.
    ec['env'].update(PIP_NO_INDEX='1', HTTP_PROXY='', HTTPS_PROXY='', ALL_PROXY='')
    write(out / 'state.json', {'status': 'starting', 'started_at': now(), 'arm': args.arm})
    started_at = now(); started_clock = time.monotonic()
    environment = None; agent = None; status = 'EnvironmentError'; result = ''; extra = None
    def task_timeout(signum, frame):
        write(out / 'timeout.json', {'status': 'Timeout', 'limit_seconds': settings()['task_timeout_seconds'],
                                    'recorded_at': now()})
        raise KeyboardInterrupt
    previous_alarm = signal.signal(signal.SIGALRM, task_timeout)
    signal.setitimer(signal.ITIMER_REAL, settings()['task_timeout_seconds'])
    try:
        environment = TaskDockerEnvironment(**ec)
        container = docker.from_env().containers.get(environment.container_id)
        initialize_task(container, official)
        proof = network_probe(container)
        proof.update(container_id=environment.container_id, container_name=container.name)
        write(out / 'network_proof.json', proof)
        agent = CapturingAgent(get_model(config=config['model']), environment, **config['agent'])
        agent.base_commit = official['base_commit']; agent.output_dir = out; agent.patch = None
        status, result = agent.run(original['problem_statement'])
    except KeyboardInterrupt:
        status = 'Timeout' if (out / 'timeout.json').exists() else 'StoppedByUser'
        result = 'Task reached the two-hour limit.' if status == 'Timeout' else 'Task stopped by user.'
    except Exception as error:
        status = type(error).__name__; result = str(error); extra = {'traceback': traceback.format_exc()}
        traceback.print_exc()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        patch = getattr(agent, 'patch', None)
        patch_available = bool(patch)
        if environment is not None and not patch:
            try:
                patch = collect_patch(environment, official['base_commit'], allow_empty=True)
                (out / 'diagnostic.patch').write_text(patch)
                if patch: check_patch(args.image, patch)
                patch_available = True
            except Exception as error:
                extra = {**(extra or {}), 'patch_capture_error': str(error)}
        if agent is not None:
            save_traj(agent, out / (args.task + '.traj.json'), exit_status=status, result=result,
                      extra_info=extra, instance_id=args.task)
        write(out / 'result.json', {'instance_id': args.task, 'arm': args.arm, 'status': status,
              'patch': patch if patch_available else '', 'patch_available': patch_available, 'finished_at': now(),
              'started_at': started_at, 'elapsed_seconds': time.monotonic() - started_clock,
              'component_usage': collect_component_usage(agent.messages) if agent else [],
              'model_calls': agent.model.n_calls if agent else 0, 'reported_cost_usd': agent.model.cost if agent else 0,
              'error': result if status != 'Submitted' else None})
        write(out / 'state.json', {'status': status, 'finished_at': now()})
        if environment: environment.cleanup()
    print(args.task, args.arm, status, flush=True)


if __name__ == '__main__': main()

"""Frozen paired trial with a predeclared full-direct-score stop rule."""
import fcntl
import os
from pathlib import Path
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'core'))
import common
import components
import environment
import evaluation
import task
from run_pipeline import costs, stage


def main():
    common.OUT.mkdir(parents=True, exist_ok=True)
    lock = (common.OUT / 'worker.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    marker = common.OUT / 'paired_manifest.json'
    if marker.exists():
        raise RuntimeError('Retain the existing attempt; no automatic retry.')
    official = common.rows()[0]
    iid = official['instance_id']
    group = common.groups()[0]
    manifest = {'started_at': common.now(), 'instance_id': iid, 'status': 'running',
        'model': common.MODEL, 'repetitions_per_arm': 1, 'selection_frozen': True,
        'protocol': 'V45 baseline-first: host source-fit review required before extraction. Same-repository old source only; original leakage gate, task prompts and budgets; repaired parser and final usage field.'}
    common.write(marker, manifest)
    try:
        env = common.model_env()  # Enforces the frozen API destination before any call.
        os.environ.update(env)
        if env.get('MODEL_NAME') and env['MODEL_NAME'] != common.MODEL:
            raise RuntimeError('Shell model differs from frozen experiment model.')
        manifest['api_base'] = env['OPENAI_API_BASE']
        stage('official_image_preparation')
        environment.prepare_runtime(official)
        proof = environment.preflight(official, official['image_name'])
        config = common.settings()
        config['groups'][0]['source_sha256'] = common.digest(common.hashes(Path(group['source_root'])))
        common.write(common.CONFIG / 'experiment.json', config)
        common.write(common.OUT / 'prepared.json', {'input_sha256': common.input_identity(),
            'official_images': {iid: proof['image_id']}, 'prepared_at': common.now()})
        common.verify_inputs()
        manifest['frozen_input_sha256'] = common.input_identity()
        stage('base_and_reference_evaluation')
        manifest['base'] = evaluation.evaluate(official, '', common.OUT / 'preflight/base')
        manifest['reference'] = evaluation.evaluate(official, official['patch'], common.OUT / 'preflight/reference')
        common.write(marker, manifest)
        if not manifest['reference']['required_tests_passed']:
            manifest.update(status='reference_preflight_failed', error='Official reference failed required tests; no model calls.')
            return
        reuse = config.get('reuse_direct_from')
        if reuse:
            old = Path(reuse)
            source = old / 'outputs/tasks/direct' / iid
            trajectory = common.read(source / (iid + '.traj.json'))
            old_model = trajectory['info']['config']['model']
            assert old_model['model_name'] == common.MODEL
            assert old_model['model_kwargs']['api_base'].rstrip('/') == env['OPENAI_API_BASE'].rstrip('/')
            assert old_model['model_kwargs']['temperature'] == 0.0
            assert common.read(old / 'inputs/agent_tasks.json') == common.read(ROOT / 'inputs/agent_tasks.json')
            assert (old / 'config/task.yaml').read_bytes() == (common.CONFIG / 'task.yaml').read_bytes()
            assert common.read(source / 'result.json')['status'] == 'Submitted'
            old_official = common.read(old / 'inputs/tasks.json')[0]
            assert old_official['base_commit'] == official['base_commit']
            old_score = common.read(source / 'evaluation/result.json')
            assert old_score['image_id'] == proof['image_id']
            destination = common.OUT / 'tasks/direct' / iid
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
            manifest['direct_reused_from'] = str(source)
            manifest['direct'] = old_score
        else:
            stage('same_model_direct_arm')
            sys.argv = [str(ROOT / 'core/task.py'), '--task', iid, '--arm', 'direct', '--image', official['image_name']]
            task.main()
            direct = common.read(common.OUT / 'tasks/direct' / iid / 'result.json')
            if direct['status'] == 'StoppedByUser':
                manifest.update(status='stopped_by_user', error='Direct task stopped by user; no evaluation or further stages.')
                return
            manifest['direct'] = evaluation.evaluate(official, direct['patch'], common.OUT / 'tasks/direct' / iid / 'evaluation')
        common.write(marker, manifest)
        if manifest['direct']['required_tests_passed']:
            manifest.update(status='direct_ceiling', error=None,
                stop_reason='Direct already passes all required tests; component pass-rate gain is impossible in this pair.')
            return
        stage('awaiting_source_fit_review')
        manifest.update(status='awaiting_source_fit_review', extraction_started=False, baseline_finished_at=common.now())
        return
    except KeyboardInterrupt:
        manifest.update(status='stopped_by_user', error='Worker interrupted; no further stages.')
    except BaseException as error:
        manifest.update(status='failed', error=str(error), exception=type(error).__name__)
        common.write(common.OUT / 'paired_error.json', {'error': str(error), 'traceback': traceback.format_exc()})
        traceback.print_exc()
    finally:
        manifest.update(finished_at=common.now(), costs=costs())
        direct = common.OUT / 'tasks/direct' / iid / 'result.json'
        if direct.exists():
            manifest['direct_model_cost_usd'] = common.read(direct).get('reported_cost_usd')
            manifest['direct_cost_incurred_in_this_run'] = not bool(manifest.get('direct_reused_from'))
        common.write(marker, manifest)
        stage(manifest['status'])


if __name__ == '__main__':
    main()

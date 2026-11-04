"""One frozen run using the existing extraction, review, task and evaluation code."""
import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'core'))
import common
import components
import environment
import evaluation
import task


def stage(name, **details):
    value = {'stage': name, 'updated_at': common.now(), **details}
    common.write(common.OUT / 'pipeline_state.json', value)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def costs():
    sources = [('extraction', p) for p in common.OUT.glob('components/*/extraction/agent_status.json')]
    sources += [('review', p) for p in common.OUT.glob('components/*/components/*/review/agent_status.json')]
    sources += [('leakage', p) for p in common.OUT.glob('components/*/components/*/leakage_response.json')]
    sources += [('inference', p) for p in common.OUT.glob('tasks/components/*/result.json')]
    records = []
    for role, path in sources:
        data = common.read(path)
        records.append({'stage': role, 'file': str(path.relative_to(ROOT)),
                        'reported_cost_usd': data.get('reported_cost_usd'),
                        'model_calls': data.get('api_calls', data.get('model_calls'))})
    by_stage = {}
    for role in ('extraction', 'review', 'leakage', 'inference'):
        rows = [r for r in records if r['stage'] == role]
        by_stage[role] = {'known_reported_cost_usd': sum(r['reported_cost_usd'] for r in rows
                                                       if r['reported_cost_usd'] is not None),
                          'unknown_cost_records': sum(r['reported_cost_usd'] is None for r in rows),
                          'record_count': len(rows),
                          'model_calls': sum(r['model_calls'] for r in rows if r['model_calls'] is not None)}
    return {'by_stage': by_stage, 'records': records,
            'known_reported_model_total_usd': sum(v['known_reported_cost_usd'] for v in by_stage.values()),
            'validation_and_runtime_compute_cost': 'unknown_not_metered',
            'cost_basis': 'model wrapper/reference pricing; not a provider invoice; unknown costs are not zero'}


def main():
    group = common.groups()[0]
    task_id = group['task_ids'][0]
    official = next(r for r in common.rows() if r['instance_id'] == task_id)
    common.OUT.mkdir(parents=True, exist_ok=True)
    marker = common.OUT / 'run_manifest.json'
    if marker.exists():
        raise RuntimeError('This full run already started; preserve it instead of silently retrying.')
    model_from_bashrc = os.environ.get('MODEL_NAME')
    if model_from_bashrc and model_from_bashrc != common.MODEL:
        raise RuntimeError('Reloaded MODEL_NAME differs from the frozen experiment model.')
    env = common.model_env()
    os.environ.update(env)
    manifest = {'started_at': common.now(), 'status': 'running', 'task_id': task_id,
                'source_commit': group['extraction_commit'], 'model': common.MODEL,
                'model_from_reloaded_bashrc': model_from_bashrc,
                'api_base_from_reloaded_bashrc': env['OPENAI_API_BASE'],
                'runtime_image': group['runtime_image'], 'network': 'none',
                'task_step_limit': 250, 'task_timeout_seconds': 7200,
                'extraction_review_step_limit': 250, 'extraction_review_wall_time_limit': None,
                'prompt_hashes': common.hashes(common.CONFIG / 'prompts'),
                'component_origin': 'fresh automatic extraction; no manual component/document revisions',
                'baseline': 'historical Curator1085 baseline 14/18 F2P, 243/243 P2P; not rerun'}
    common.write(marker, manifest)
    try:
        stage('preflight')
        import docker
        image_id = docker.from_env().images.get(group['runtime_image']).id
        proof = environment.preflight(official, group['runtime_image'])
        if proof['image_id'] != image_id:
            raise RuntimeError('Official image changed during preflight')
        if common.digest(common.hashes(Path(group['source_root']))) != group['source_sha256']:
            raise RuntimeError('Frozen base source differs')
        common.write(common.OUT / 'prepared.json', {'input_sha256': common.input_identity(),
                     'official_images': {task_id: image_id}, 'prepared_at': common.now()})
        common.verify_inputs()
        stage('fresh_extraction_review_validation_publication')
        sys.argv = [str(ROOT / 'core/components.py'), '--group', group['group_id']]
        components.main()
        bundle_info = common.read(common.OUT / 'bundle_index' / (group['group_id'] + '.json'))
        bundle = Path(bundle_info['bundle'])
        if common.digest(common.hashes(bundle)) != bundle_info['sha256']:
            raise RuntimeError('Bundle changed after publication')
        manifest.update(bundle=str(bundle), bundle_sha256=bundle_info['sha256'],
                        published_components=common.read(bundle / 'manifest.json')['components'])
        common.write(marker, manifest)
        stage('task_inference', bundle=str(bundle), component_count=bundle_info['component_count'])
        sys.argv = [str(ROOT / 'core/task.py'), '--task', task_id, '--arm', 'components',
                    '--image', group['runtime_image'], '--bundle', str(bundle)]
        task.main()
        inference = common.read(common.OUT / 'tasks/components' / task_id / 'result.json')
        stage('official_evaluation', inference_status=inference['status'])
        output = common.OUT / 'tasks/components' / task_id / 'evaluation'
        patch = inference.get('patch') if inference.get('patch_available') else None
        result = (evaluation.evaluate(official, patch, output, bundle) if patch else
                  evaluation.not_evaluated(official, output, inference.get('error') or 'No recoverable task patch'))
        manifest.update(status='completed', inference_status=inference['status'],
                        required_tests_passed=result['required_tests_passed'],
                        evaluation=result, finished_at=common.now())
        stage('completed', required_tests_passed=result['required_tests_passed'])
    except BaseException as error:
        manifest.update(status='stopped' if isinstance(error, KeyboardInterrupt) else 'failed',
                        error=str(error), exception=type(error).__name__, finished_at=common.now())
        common.write(common.OUT / 'pipeline_error.json', {'exception': type(error).__name__,
                     'message': str(error), 'traceback': traceback.format_exc()})
        stage(manifest['status'], exception=type(error).__name__, error=str(error))
        raise
    finally:
        manifest['costs'] = costs()
        common.write(marker, manifest)
        common.write(common.OUT / 'cost_summary.json', manifest['costs'])


if __name__ == '__main__':
    main()

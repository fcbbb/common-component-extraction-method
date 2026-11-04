"""Existing review structural checks returned before submission acceptance."""

def build_review_checker(shared_source):
    """Inject stdlib-only source-span checks into the existing file protocol."""
    assert shared_source.count('\ndef main() -> int:') == 1
    assert shared_source.count('        load_submission(args.output, args.role)') == 1
    # This checker runs under the original images, including Python 3.7.
    shared_source = shared_source.replace(
        'cursor.resolve().is_relative_to(root.resolve())', '_inside(cursor.resolve(), root.resolve())')
    addition = '''
def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

def _review_source_feedback(result, role):
    if role != 'review':
        return
    root = Path('/testbed').resolve()
    component = json.loads((root / 'component_bundle/component.json').read_text())
    validate_review_revision(component, result.get('revision'), (root / 'component_bundle/common.py').read_text())
    allowed = {(m['file_id'], m['unit_id']) for m in component['members']}
    for member in result.get('confirmed_members', []):
        if (member.get('file_id'), member.get('unit_id')) not in allowed:
            raise ValueError('confirmed_members must retain a supplied member identifier exactly')
    names = {e['name'] for e in component['entrypoints']}
    plan = result.get('smoke_test', result)
    cases = plan.get('cases', [])
    ids = {}
    for case in cases:
        cid = case.get('case_id')
        if not isinstance(cid, str) or not cid or cid in ids:
            raise ValueError('smoke cases need unique case_id values')
        if case.get('entrypoint') not in names:
            raise ValueError('smoke case entrypoint must be a supplied entrypoint name')
        ids[cid] = case['entrypoint']
    for cap in result.get('entrypoint_capabilities', []):
        if cap['entrypoint'] not in names or (cap['method'] and not cap['method'].isidentifier()):
            raise ValueError('use a supplied entrypoint name and an unqualified method name')
        if any(ids.get(cid) != cap['entrypoint'] for cid in cap.get('case_ids', [])):
            raise ValueError('capability case_ids must identify cases for the same entrypoint')
    spans = [(citation, True) for citation in result.get('evidence', [])]
    spans += [(citation, False) for citation in plan.get('sources', [])]
    for case in cases:
        spans += [(citation, False) for citation in case.get('sources', [])]
    for citation, artifact_allowed in spans:
        path = citation.get('file_id')
        start, end = citation.get('line_start'), citation.get('line_end')
        if (not isinstance(path, str) or Path(path).is_absolute() or '..' in Path(path).parts
                or type(start) is not int or type(end) is not int or start < 1 or end < start):
            raise ValueError('source citations need a repository-relative path and positive inclusive line bounds')
        if Path(path).parts[:1] == ('component_bundle',) and not (artifact_allowed and path == 'component_bundle/common.py'):
            raise ValueError('smoke citations must refer to original repository source')
        source = (root / path).resolve()
        if not _inside(source, root) or not source.is_file():
            raise ValueError('citation source does not exist: ' + path)
        length = len(source.read_text().splitlines())
        if end > length:
            raise ValueError('citation ' + path + ':' + str(start) + '-' + str(end)
                             + ' exceeds the file length ' + str(length) + '; reread the source and correct the span')

'''
    shared_source = shared_source.replace('\ndef main() -> int:', addition + '\ndef main() -> int:')
    return shared_source.replace('        load_submission(args.output, args.role)',
                                 '        result = load_submission(args.output, args.role)\n        _review_source_feedback(result, args.role)')

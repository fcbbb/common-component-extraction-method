"""Keep the generated review schema consistent with opaque candidate IDs."""
import json
import re


_MEMBER_EXAMPLE = re.compile(
    r'"confirmed_members":\s*\[\s*\{\s*'
    r'"file_id":\s*"relative/path.py",\s*'
    r'"unit_id":\s*"function:name"\s*\}\s*\]')


def exact_member_review_task(task, members, instructions):
    if not members or not all(isinstance(m, dict) and isinstance(m.get('file_id'), str)
                              and isinstance(m.get('unit_id'), str) for m in members):
        raise ValueError('Review requires candidate member identifiers.')
    example = {k: members[0][k] for k in ('file_id', 'unit_id')}
    replacement = '"confirmed_members": ' + json.dumps([example], ensure_ascii=False, indent=2)
    task, count = _MEMBER_EXAMPLE.subn(lambda _: replacement, task)
    if count != 1:
        raise ValueError('Expected exactly one generated review member schema example.')
    return task.rstrip() + '\n\n' + instructions.strip() + '\n'

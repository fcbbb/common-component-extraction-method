"""Collect the task agent's optional usage field, without verifying adoption."""
import json
import re

USAGE_NOTE = ('In your final task-submission response, if you used a delivered component, include '
              '`{"component_usage": ["component identifier / entrypoint"]}` '
              'on a separate line outside the Bash block; otherwise omit it. '
              'Keep the existing final submission command in that same response, without an extra turn.')


def collect_component_usage(messages):
    """Read agent-reported identifiers from the last assistant response only.

    Known action payloads and Markdown code blocks are excluded so a JSON
    example written to a file is not confused with a report to the runner.
    Missing or malformed optional metadata must not interrupt task execution.
    """
    usage = []
    final_response = next((message for message in reversed(messages)
                           if message.get('role') == 'assistant'), None)
    if final_response is None:
        return usage
    for message in [final_response]:
        content = message.get('content', '')
        if not isinstance(content, str):
            continue
        command = message.get('extra', {}).get('parsed_action', {}).get('command')
        if command:
            content = content.replace(command, '')
        elif re.search(r'<[^>]*\b(?:invoke|parameter)\b', content):
            # Without a parsed command boundary, do not interpret metadata
            # inside a rejected native tool response as a usage declaration.
            continue
        content = re.sub(r'```[^\n]*\n.*?(?:```|\Z)', '', content, flags=re.DOTALL)
        for line in content.splitlines():
            if not line.lstrip().startswith('{'):
                continue
            try:
                value = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict) or set(value) != {'component_usage'}:
                continue
            entries = value['component_usage']
            if not isinstance(entries, list) or not all(isinstance(item, str) and item.strip() for item in entries):
                continue
            for entry in entries:
                entry = entry.strip()
                if entry not in usage:
                    usage.append(entry)
    return usage


def install_usage_recording(run):
    """Add only the optional field and one prompt sentence in a fresh run."""
    from pathlib import Path

    run = Path(run)
    task = run / 'core/task.py'
    source = task.read_text()
    import_line = 'from component_usage import collect_component_usage\n'
    if import_line not in source:
        anchor = 'from action_protocol import CompatibleActionAgent\n'
        if source.count(anchor) != 1:
            raise ValueError('Unexpected task runtime import structure.')
        source = source.replace(anchor, anchor + import_line, 1)
    field = "              'component_usage': collect_component_usage(agent.messages) if agent else [],\n"
    if field not in source:
        anchor = "              'model_calls': agent.model.n_calls"
        if source.count(anchor) != 1:
            raise ValueError('Unexpected task result structure.')
        source = source.replace(anchor, field + anchor, 1)
    prompt = run / 'config/prompts/usage/agent_bundle_prompt.txt'
    prompt_text = prompt.read_text()
    if USAGE_NOTE not in prompt_text:
        prompt_text = prompt_text.rstrip('\n') + '\n\n' + USAGE_NOTE + '\n'
    task.write_text(source)
    prompt.write_text(prompt_text)

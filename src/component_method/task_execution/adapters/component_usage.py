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

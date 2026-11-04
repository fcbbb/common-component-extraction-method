"""Parse known DeepSeek transport variants without changing command content.

API requests and the mini-swe-agent loop stay unchanged. Token spelling, compact
markup and observed mixed delimiters are handled locally. Ambiguity remains an
error, and original responses stay in the audit trajectory.
"""
import re
from minisweagent.agents.default import DefaultAgent, FormatError

# HF DeepSeek-V4-Pro discussion 209: doubled ASCII/full-width pipes, including
# whitespace between pipes. Recognize these in control tags, not in command data.
_MARKER = r'(?:[|｜]\s*){1,2}DSML\s*(?:[|｜]\s*){1,2}'
_EOS = r'(?:<｜end▁of▁sentence｜>)?'
_BASH = re.compile(r'```bash\s*\n(.*?)\n```', re.DOTALL)
_BASH_START = re.compile(r'```bash\s*\n')
_TAG = re.compile(rf'<\s*/?\s*{_MARKER}\s*[A-Za-z_]')
_OPEN_TAG = re.compile(rf'<\s*{_MARKER}\s*[A-Za-z_]')
_BARE_TAG = re.compile(r'<\s*/?\s*(?:parameter|invoke)\b')
_OUTER = re.compile(rf'<\s*/?\s*{_MARKER}\s*(?:calls|tool_calls)\s*>')
_FRAME = re.compile(rf'<\s*{_MARKER}\s*(?P<wrapper>calls|tool_calls)\s*>\s*(?P<body>.*?)\s*</\s*{_MARKER}\s*(?P=wrapper)\s*>', re.DOTALL)
_INVOKE_HEAD = re.compile(rf'<\s*{_MARKER}\s*invoke(?P<attrs>[^<>]*)>')
_INVOKE = re.compile(rf'<\s*{_MARKER}\s*invoke(?P<attrs>[^<>]*)>\s*(?P<body>.*?)\s*</\s*(?:{_MARKER}\s*)?invoke\s*>', re.DOTALL)
_PARAMETER = re.compile(rf'<\s*(?:{_MARKER}\s*)?parameter(?P<attrs>[^<>]*)>(?P<command>.*?)</\s*(?:{_MARKER}\s*)?parameter\s*>', re.DOTALL)
_PARAMETER_HEAD = re.compile(rf'<\s*(?:{_MARKER}\s*)?parameter(?P<attrs>[^<>]*)>')
_BARE_PARAMETER = re.compile(r'<parameter(?P<attrs>[^<>]*)>(?P<command>.*?)</parameter>', re.DOTALL)
_ATTRIBUTE = re.compile(r'''\s+([A-Za-z_]\w*)\s*=\s*(?:"([^"]*)"|'([^']*)')''')
_HYBRID_TAIL = re.compile(rf'</\s*{_MARKER}\s*parameter\s*>\s*</\s*{_MARKER}\s*invoke\s*>\s*</\s*{_MARKER}\s*(?:calls|tool_calls)\s*>\s*{_EOS}\s*$', re.DOTALL)
_FENCE_TAIL = re.compile(rf'\n```\s*{_EOS}\s*$', re.DOTALL)
_RECOVERY_OPEN = re.compile(
    rf'<\s*{_MARKER}\s*(?P<kind>calls|tool_calls|invoke)\b(?P<attrs>[^<>]*)>'
)
# A closed parameter or a hybrid closing delimiter already bounds the command.
# Missing/abbreviated *outer* closing tags do not require modifying that command.
_RECOVERY_CLOSE = rf'</\s*(?:{_MARKER}\s*(?:invoke|inv|calls|tool_calls)?|invoke)\s*>'
_RECOVERY_SUFFIX = re.compile(rf'(?:\s*{_RECOVERY_CLOSE}){{0,4}}\s*{_EOS}\s*$', re.DOTALL)
_HYBRID_BOUNDARY = re.compile(rf'</\s*{_MARKER}\s*(?:parameter)?\s*>')


def _attributes(text):
    attributes = {}; cursor = 0
    for match in _ATTRIBUTE.finditer(text):
        if text[cursor:match.start()].strip() or match[1] in attributes:
            raise ValueError('Invalid or duplicate tool attributes.')
        attributes[match[1]] = match[2] if match[2] is not None else match[3]
        cursor = match.end()
    if text[cursor:].strip(): raise ValueError('Invalid tool attributes.')
    return attributes


def _tool(attrs):
    if _attributes(attrs) not in ({'name': 'bash'}, {'name': 'shell'}):
        raise ValueError('Only one bash/shell invocation is supported.')


def _command(parameter, *, aliases=False):
    attrs = _attributes(parameter['attrs'])
    allowed = {'command', 'bash'} if aliases else {'command'}
    if (attrs.get('name') not in allowed or set(attrs) - {'name', 'string'}
            or attrs.get('string', 'true') != 'true'):
        raise ValueError('Expected a raw-string command parameter without unknown fields.')
    command = parameter['command'].strip()
    fenced = _BASH.fullmatch(command)
    if fenced is not None:
        command = fenced[1].strip()
    if not command or _TAG.search(command) or _BARE_TAG.search(command):
        raise ValueError('Empty or nested tool commands are not supported.')
    return command


def _outside(text, *, outer=False):
    if outer:
        if len(list(_OUTER.finditer(text))) > 2:
            raise ValueError('Multiple outer tool wrappers are not supported.')
        text = _OUTER.sub('', text)
    if _TAG.search(text) or _BARE_TAG.search(text) or _BASH_START.search(text):
        raise ValueError('Additional or ambiguous action envelopes are not supported.')


def _strict_tool_command(content):
    """Return (unchanged command, recognized transport), or reject ambiguity."""
    frames = list(_FRAME.finditer(content))
    if frames:
        if len(frames) != 1: raise ValueError('Expected exactly one tool-call block.')
        frame = frames[0]; _outside(content[:frame.start()] + content[frame.end():])
        invocation = _INVOKE.fullmatch(frame['body'].strip())
        if invocation is None: raise ValueError('Expected exactly one complete bash/shell invocation.')
        _tool(invocation['attrs'])
        parameter = _PARAMETER.fullmatch(invocation['body'].strip())
        if parameter is None: raise ValueError('Expected exactly one complete command parameter.')
        return _command(parameter), 'dsml'

    # A complete inner invoke supplies a boundary even without its outer wrapper.
    invocations = list(_INVOKE.finditer(content))
    if invocations:
        if len(invocations) != 1: raise ValueError('Multiple tool invocations are not supported.')
        invocation = invocations[0]
        _outside(content[:invocation.start()] + content[invocation.end():], outer=True)
        _tool(invocation['attrs'])
        parameter = _PARAMETER.fullmatch(invocation['body'].strip())
        if parameter is None: raise ValueError('Expected exactly one complete command parameter.')
        return _command(parameter), 'dsml_inner_recovered'

    # Observed hybrid: Markdown opener, complete native closing sequence.
    bash_heads = list(_BASH_START.finditer(content)); tail = _HYBRID_TAIL.search(content)
    if bash_heads and tail:
        if len(bash_heads) != 1 or bash_heads[0].end() > tail.start():
            raise ValueError('Ambiguous mixed Bash/DSML response.')
        head = bash_heads[0]; _outside(content[:head.start()])
        command = content[head.end():tail.start()].strip()
        if not command or _TAG.search(command) or _BARE_TAG.search(command) or '```' in command:
            raise ValueError('Ambiguous mixed Bash/DSML command.')
        return command, 'bash_dsml_tail_recovered'

    # Reverse hybrid: native header, closed command parameter, closing fence.
    heads = list(_INVOKE_HEAD.finditer(content)); fence = _FENCE_TAIL.search(content)
    if heads and fence:
        if len(heads) != 1 or heads[0].end() > fence.start():
            raise ValueError('Ambiguous mixed DSML/Bash response.')
        head = heads[0]; _outside(content[:head.start()], outer=True); _tool(head['attrs'])
        parameter = _PARAMETER.fullmatch(content[head.end():fence.start()].strip())
        if parameter is None: raise ValueError('Mixed response has no closed command parameter.')
        return _command(parameter), 'dsml_fence_tail_recovered'

    # A sole command XML field is another observed response of this Bash-only
    # agent. An identical command/bash shadow pair is executed exactly once.
    parameters = list(_BARE_PARAMETER.finditer(content))
    if parameters:
        commands = [_command(p, aliases=True) for p in parameters]
        names = [_attributes(p['attrs'])['name'] for p in parameters]
        if len(parameters) > 1 and ('command' not in names or len(set(commands)) != 1):
            raise ValueError('Different or ambiguous duplicate command parameters.')
        outside = _BARE_PARAMETER.sub('', content)
        if len(parameters) > 1: outside = outside.replace('</parameter>', '', 1)
        _outside(outside)
        return commands[0], 'xml_parameter_recovered'
    raise ValueError('No complete, unambiguous action was found.')


def _recovery_prefix(prefix):
    """Permit prose and at most one known wrapper and one bash/shell header."""
    openings = list(_RECOVERY_OPEN.finditer(prefix))
    kinds = [item['kind'] for item in openings]
    if kinds not in ([], ['calls'], ['tool_calls'], ['invoke'],
                     ['calls', 'invoke'], ['tool_calls', 'invoke']):
        raise ValueError('Multiple or reordered tool headers are ambiguous.')
    for item in openings:
        if item['kind'] == 'invoke':
            _tool(item['attrs'])
        elif item['attrs'].strip():
            raise ValueError('Unknown tool wrapper attributes.')
    _outside(_RECOVERY_OPEN.sub('', prefix))


def _recover_bounded_command(content):
    """Recover damaged envelopes only when an explicit command end remains.

    Never infer missing shell text, decode XML entities, or replace strings in
    the command. A unique complete parameter is sufficient even when its outer
    invoke/calls closers are missing or abbreviated.
    """
    parameters = list(_PARAMETER.finditer(content))
    if len(parameters) == 1:
        parameter = parameters[0]
        _recovery_prefix(content[:parameter.start()])
        if _RECOVERY_SUFFIX.fullmatch(content[parameter.end():]) is None:
            raise ValueError('Unrecognized text after the closed command parameter.')
        return _command(parameter), 'closed_parameter_envelope_recovered'
    if parameters:
        raise ValueError('Multiple command parameters remain ambiguous.')

    # Observed native variant: a complete parameter opener followed by an
    # anonymous DSML closer. That explicit delimiter still bounds the payload.
    parameter_heads = list(_PARAMETER_HEAD.finditer(content))
    if parameter_heads:
        if len(parameter_heads) != 1:
            raise ValueError('Multiple command parameter headers remain ambiguous.')
        head = parameter_heads[0]
        _recovery_prefix(content[:head.start()])
        for boundary in _HYBRID_BOUNDARY.finditer(content, head.end()):
            if _RECOVERY_SUFFIX.fullmatch(content[boundary.end():]) is not None:
                parameter = {'attrs': head['attrs'],
                             'command': content[head.end():boundary.start()]}
                return _command(parameter), 'bounded_parameter_closer_recovered'
        raise ValueError('Command parameter has no explicit end delimiter.')

    heads = list(_BASH_START.finditer(content))
    if len(heads) != 1:
        raise ValueError('Expected one complete parameter or one hybrid Bash opener.')
    head = heads[0]
    _outside(content[:head.start()])
    boundaries = [boundary for boundary in _HYBRID_BOUNDARY.finditer(content, head.end())
                  if _RECOVERY_SUFFIX.fullmatch(content[boundary.end():]) is not None]
    if len(boundaries) != 1:
        raise ValueError('No unique hybrid command end was found.')
    command = content[head.end():boundaries[0].start()].strip()
    if not command or _TAG.search(command) or _BARE_TAG.search(command) or '```' in command:
        raise ValueError('Nested or ambiguous hybrid command data.')
    return command, 'bounded_bash_dsml_tail_recovered'


def parsed_tool_command(content):
    """Return unchanged command text from a strict or uniquely bounded frame."""
    try:
        return _strict_tool_command(content)
    except ValueError as original:
        try:
            return _recover_bounded_command(content)
        except ValueError:
            raise original


def dsml_command(content):
    return parsed_tool_command(content)[0]


class CompatibleActionAgent(DefaultAgent):
    def parse_action(self, response):
        content = response['content']; bash = list(_BASH.finditer(content))
        frames = list(_FRAME.finditer(content))
        native_primary = len(frames) == 1 and all(frames[0].start() <= b.start() and b.end() <= frames[0].end() for b in bash)
        protocol = 'bash'
        if native_primary or (not bash and (_TAG.search(content) or _BARE_TAG.search(content))):
            try: command, protocol = parsed_tool_command(content)
            except ValueError as error:
                raise FormatError(str(error) + ' Return exactly one complete Bash block.') from error
            action = {**response, 'action': command}
        elif bash:
            outside = _BASH.sub('', content)
            action = super().parse_action(response)
            if _OPEN_TAG.search(outside) or _BARE_PARAMETER.search(outside):
                # Duplicate representations are fine only if they identify the
                # same complete command. Never silently choose between actions.
                try:
                    shadow, _ = parsed_tool_command(outside)
                except ValueError as error:
                    raise FormatError('Incomplete or ambiguous additional action. '
                                      'Return exactly one complete Bash block.') from error
                if shadow != action['action']:
                    raise FormatError('Conflicting Bash and tool commands. '
                                      'Return exactly one complete Bash block.')
                protocol = 'bash_with_matching_tool_shadow'
        else: action = super().parse_action(response)
        if self.messages and self.messages[-1].get('role') == 'assistant' and self.messages[-1].get('content') == content:
            self.messages[-1].setdefault('extra', {})['parsed_action'] = {'protocol': protocol, 'command': action['action']}
        return action

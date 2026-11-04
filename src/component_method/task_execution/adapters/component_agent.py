"""Use mini-swe-agent 1.14's official loop with the component file protocol.

Version 1.14's mini CLI has neither environment selection nor layered configs.
Its Environment.execute takes a command string and completion is checked by
the agent, rather than the environment. This adapter supplies those interfaces
without changing model parameters or the extraction/review/validation criteria.
"""
import argparse
import json
from dataclasses import fields
from pathlib import Path
import os
import shlex
import traceback

import yaml
from minisweagent.agents.default import AgentConfig, NonTerminatingException, TerminatingException
from minisweagent.config import builtin_config_dir
from minisweagent.models import get_model
from minisweagent.run.utils.save import save_traj
from component_method.task_execution.runtime_support.docker_environment import ComponentAgentDockerEnvironment, TOOL_ENV
from component_method.component_build.submission import CHECKER_PATH, OUTPUT_DIRECTORY
from action_protocol import CompatibleActionAgent


class CheckedEnvironment(ComponentAgentDockerEnvironment):
    def execute(self, command, cwd='', *, timeout=None):
        return super().execute({'command':command},cwd,timeout=timeout)

    def _check_finished(self, output):
        lines=output.get('output','').lstrip().splitlines()
        markers=['COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT','MINI_SWE_AGENT_FINAL_OUTPUT']
        finishing=any(line.strip() in markers for line in lines)
        if not finishing:return
        check=f'python {CHECKER_PATH} --role {shlex.quote(self.output_role)} --output {OUTPUT_DIRECTORY}'
        check=self.runtime_activation+' && '+check
        result=self.client.containers.get(self.container_name).exec_run(['/bin/bash','-lc',check],user='10001:10001',environment=TOOL_ENV)
        if output.get('returncode') or result.exit_code:
            output['output']='Submission rejected; correct the files and check again.\n'+result.output.decode(errors='replace')
            output['returncode']=result.exit_code or output['returncode']
            return
        output['output']='COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n{"transport":"files"}\n'


def merge(target,other):
    for key,value in other.items():
        if isinstance(value,dict) and isinstance(target.get(key),dict):merge(target[key],value)
        else:target[key]=value


def check_role_input(config, task, role, expected):
    if role not in ('extraction', 'review'):
        return
    assert config['agent']['instance_template'] == '{{task}}'
    assert task.encode() == (expected / 'user.txt').read_bytes(), 'Effective ' + role + ' user prompt differs'
    assert config['agent']['system_template'].strip() == (expected / 'system.txt').read_text().strip(), 'Effective ' + role + ' system differs'


def run_agent(agent, task):
    resume_path = os.environ.get('COMPONENT_RESUME_TRAJECTORY')
    if not resume_path:
        return agent.run(task)
    previous = json.loads(Path(resume_path).read_text())
    messages = previous.get('messages')
    if not isinstance(messages, list) or not messages:
        raise ValueError('Resume trajectory has no messages')
    stats = previous.get('info', {}).get('model_stats', {})
    agent.extra_template_vars |= {'task': task}
    agent.messages = messages
    agent.model.cost = float(stats.get('instance_cost') or 0)
    agent.model.n_calls = int(stats.get('api_calls') or 0)
    while True:
        try:agent.step()
        except NonTerminatingException as e:agent.add_message('user',str(e))
        except TerminatingException as e:
            agent.add_message('user',str(e));return type(e).__name__,str(e)


def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--task',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--input-snapshot',type=Path,required=True);p.add_argument('--config',action='append',type=Path,required=True);args=p.parse_args()
    config={}
    for path in args.config:merge(config,yaml.safe_load(path.read_text()))
    # Restore the official v1.14 bash action format around the unchanged role
    # instructions. v1.14 cannot consume the newer native action interface.
    official=yaml.safe_load((builtin_config_dir/'mini.yaml').read_text())
    config['agent']['system_template']=official['agent']['system_template']+'\n\n'+config['agent']['system_template']
    # The outer runner controls total runtime. v1.14 does not implement
    # wall_time_limit_seconds; both roles now use only the 250-step limit.
    allowed={f.name for f in fields(AgentConfig)}
    agent_config={k:v for k,v in config['agent'].items() if k in allowed}
    rejected=set(config['agent'])-allowed-{'wall_time_limit_seconds','mode','confirm_exit','whitelist_actions'}
    if rejected:raise ValueError(f'Unsupported non-default agent settings: {sorted(rejected)}')
    if config['agent'].get('wall_time_limit_seconds',0):raise ValueError('Unsupported wall-time override')
    check_role_input(config, args.task, os.environ.get('COMPONENT_OUTPUT_ROLE', ''), args.input_snapshot)
    environment=CheckedEnvironment(**config['environment'])
    agent=CompatibleActionAgent(get_model(args.model,config.get('model',{})),environment,**agent_config)
    status,result,extra=None,None,None
    try:status,result=run_agent(agent,args.task)
    except Exception as e:
        status,result=type(e).__name__,str(e);extra={'traceback':traceback.format_exc()}
        traceback.print_exc()
    finally:save_traj(agent,args.output,exit_status=status,result=result,extra_info=extra)
    if status!='Submitted':raise SystemExit(1)


if __name__=='__main__':main()

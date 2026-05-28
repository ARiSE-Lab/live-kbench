# kenv-invoker.py
# Run initialize, setup SWE-agent, and write the final patch back.

# kEnv takes the following environment variables / volumes:
# - KENV_COMMIT_FROM: Literal['crash', 'parent']
# - KENV_SYZBOT_BUG_ID: str
# - KENV_STATEFUL_EDIT: bool (false by default)
# - KENV_KGYM_ENDPOINT: str, kGym API URL (optional) for stateful edit
# - kGym storage config file at /KBDr/storageCfg.json
# - kBench json (SyzbotData and kCacheIndex) file at /KBDr/kBench.json
# - kBench evaluation results (kBenchEvaluationResult) file at /KBDr/kEval.json
# - Linux kernel repository mirror folder at /KBDr/mirror (see kGym/kclient/repositories for details)
# - /KBDr/agent-config
# - /KBDr/model-config
# Output space:
# /KBDr/output/{patch.txt, traj.json, log.txt};

import os, yaml, subprocess, json, time
from pathlib import Path

from KBDr.kclient.agentic import filter_binary_files_from_patch

EXTERNAL_CONFIG_PATH = Path('/KBDr/agent-config')
EXTERNAL_MODEL_CONFIG_PATH = Path('/KBDr/model-config')

# Setup problem statement, output folders, etc.
INTERNAL_CONFIG_PATH = Path('/tmp/agent-config')
CRASH_REPORT_PATH = Path('/root/report.txt')
REPRODUCER_PATH = Path('/root/reproducer.txt')
ORACLE_LIST_PATH = Path('/KBDr/oracle-files.txt')
KENV_SYZBOT_BUG_ID = os.environ['KENV_SYZBOT_BUG_ID']

TMP_OUTPUT_PATH = Path('/tmp/output')

OUTPUT_PATH = Path('/KBDr/output')
PATCH_PATH = OUTPUT_PATH / 'patch.txt'
TRAJ_PATH = OUTPUT_PATH / 'traj.json'
LOG_PATH = OUTPUT_PATH / 'log.txt'

def trim_text(text: str, max_chars_per_line: int = 150) -> str:
    lines = text.splitlines()
    ret = []
    for ln in lines:
        if len(ln) > max_chars_per_line:
            ret.append(ln[:max_chars_per_line] + '...')
        else:
            ret.append(ln)
    return '\n'.join(ret)

if __name__ == '__main__':
    assert os.system('/KBDr/initialize') == 0

    # Check for oracle mode from environment variable
    oracle_mode = os.environ.get('KENV_ORACLE_MODE', 'false').lower() == 'true'

    # Exit with 1 if oracle mode is on but oracle file doesn't exist
    if oracle_mode and not ORACLE_LIST_PATH.exists():
        print(f"ERROR: oracle mode is on but oracle file not found at {ORACLE_LIST_PATH}", flush=True)
        quit(1)

    task = f"""<crashReport>
{CRASH_REPORT_PATH.read_text()}
</crashReport>
<reproducer>
{trim_text(REPRODUCER_PATH.read_text())}
</reproducer>
"""

    if oracle_mode:
        task += f"""<oracleFiles>
A kernel expert has figured out that the following files need to be modified in order to fix this bug:
{ORACLE_LIST_PATH.read_text()}
</oracleFiles>"""

    internal_config = {
        'env': {
            'deployment': {
                'type': 'local'
            },
            'repo': {
                'type': 'preexisting',
                'repo_name': '/linux',
                'reset': False
            }
        },
        # 'agent': external config will provide this;
        'output_dir': str(TMP_OUTPUT_PATH),
        'problem_statement': {
            'type': 'text',
            'id': KENV_SYZBOT_BUG_ID,
            'text': task
        }
    }

    INTERNAL_CONFIG_PATH.write_text(yaml.dump(internal_config))

    # run sweagent;
    start_time = time.time()
    proc = subprocess.Popen(
        [
            'sweagent', 'run',
            '--config', str(EXTERNAL_CONFIG_PATH),
            '--config', str(EXTERNAL_MODEL_CONFIG_PATH),
            '--config', str(INTERNAL_CONFIG_PATH)
        ],
        stdin=subprocess.DEVNULL
    )
    code = proc.wait()
    end_time = time.time()

    # collect resources;
    pred = TMP_OUTPUT_PATH / KENV_SYZBOT_BUG_ID / f'{KENV_SYZBOT_BUG_ID}.pred'
    traj = TMP_OUTPUT_PATH / KENV_SYZBOT_BUG_ID / f'{KENV_SYZBOT_BUG_ID}.traj'
    trace = TMP_OUTPUT_PATH / KENV_SYZBOT_BUG_ID / f'{KENV_SYZBOT_BUG_ID}.trace.log'

    if pred.exists():
        patch = json.loads(pred.read_text()).get('model_patch', '') or ''
        patch = filter_binary_files_from_patch(patch)
        PATCH_PATH.write_text(patch)
    if traj.exists():
        TRAJ_PATH.write_text(traj.read_text())
    if trace.exists():
        LOG_PATH.write_text(trace.read_text())

    # Generate metadata.json
    try:
        if not traj.exists():
            print(f"ERROR: trajectory file not found at {traj}", flush=True)
            quit(1)

        traj_data = json.loads(traj.read_text())

        # Extract cost and exit_status from trajectory
        if 'info' not in traj_data:
            print("ERROR: 'info' key not found in trajectory", flush=True)
            quit(1)

        info = traj_data['info']

        # Extract dollarCost from model_stats
        if 'model_stats' not in info:
            print("ERROR: model_stats not found in trajectory", flush=True)
            quit(1)

        dollar_cost = info['model_stats']['instance_cost']

        # Extract timeCost (in seconds)
        time_cost = end_time - start_time

        # Extract exit_status and map to exitReason
        if 'exit_status' not in info:
            print("ERROR: exit_status not found in trajectory", flush=True)
            quit(1)
        exit_status = info['exit_status']

        # Map exit_status to exitReason using startswith for robustness
        if exit_status.startswith('submitted'):
            exit_reason = 'normal'
        elif exit_status.startswith('exit_cost'):
            exit_reason = 'costLimitExceeded'
        elif exit_status.startswith('exit_total_execution_time') or exit_status.startswith('exit_command_timeout'):
            exit_reason = 'timeLimitExceeded'
        else:
            # Unknown or error exit_status (exit_forfeit, exit_command, exit_context, exit_api, etc.)
            print(f"ERROR: Unknown/error exit_status: {exit_status}", flush=True)
            quit(1)

        # Write metadata.json
        metadata = {
            'dollarCost': dollar_cost,
            'timeCost': time_cost,
            'exitReason': exit_reason
        }
        metadata_path = OUTPUT_PATH / 'metadata.json'
        metadata_path.write_text(json.dumps(metadata, indent=2))

        print(f"Generated metadata: {metadata}", flush=True)

    except Exception as e:
        print(f"ERROR: Failed to generate metadata.json: {e}", flush=True)
        import traceback
        traceback.print_exc()
        quit(1)

    quit(code)
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

import os, yaml, subprocess, json, time, traceback
from pathlib import Path

from KBDr.kclient.agentic import filter_binary_files_from_patch
from minisweagent.models import get_model
from minisweagent.environments.local import LocalEnvironment
from minisweagent.agents.default import DefaultAgent
from minisweagent.run.utils.save import save_traj

EXTERNAL_CONFIG_PATH = Path('/KBDr/agent-config')
EXTERNAL_MODEL_CONFIG_PATH = Path('/KBDr/model-config')
KBENCH_PATH = Path('/KBDr/kBench.json')

# Setup problem statement, output folders, etc.

INTERNAL_CONFIG_PATH = Path('/tmp/agent-config.yaml')
CRASH_REPORT_PATH = Path('/root/report.txt')
REPRODUCER_PATH = Path('/root/reproducer.txt')
ORACLE_LIST_PATH = Path('/KBDr/oracle-files.txt')
KENV_SYZBOT_BUG_ID = os.environ['KENV_SYZBOT_BUG_ID']

REPO_PATH = '/linux'

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

def get_patch():
    proc = subprocess.Popen(
        ['git', 'add', '-A'],
        cwd=REPO_PATH,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL
    )
    assert proc.wait() == 0
    proc = subprocess.Popen(
        ['git', 'diff', '--cached'],
        cwd=REPO_PATH,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL
    )
    patch, _ = proc.communicate()
    assert proc.wait() == 0
    return patch.decode('utf-8')

if __name__ == '__main__':
    assert os.system('/KBDr/initialize') == 0

    config: dict = yaml.safe_load(EXTERNAL_CONFIG_PATH.read_text())
    oracle_mode = os.environ.get('KENV_ORACLE_MODE', 'false').lower() == 'true'

    # Exit with 1 if oracle mode is on but oracle file doesn't exist
    if oracle_mode and not ORACLE_LIST_PATH.exists():
        print(f"ERROR: oracle mode is on but oracle file not found at {ORACLE_LIST_PATH}", flush=True)
        quit(1)

    config['env']['cwd'] = '/linux'

    config['model'] = (yaml.safe_load(EXTERNAL_MODEL_CONFIG_PATH.read_text()))['model']

    INTERNAL_CONFIG_PATH.write_text(yaml.dump(config))

    # Extract context vars for template rendering
    crash_report = CRASH_REPORT_PATH.read_text()
    CRASH_REPORT_PATH.unlink()
    reproducer = trim_text(REPRODUCER_PATH.read_text())
    oracle_section = ''
    if oracle_mode:
        oracle_section = (
            f'<oracleFiles>\nA kernel expert has figured out that the following files need to be '
            f'modified in order to fix this bug:\n{ORACLE_LIST_PATH.read_text()}\n</oracleFiles>\n'
        )

    context_kwargs = dict(
        crash_report=crash_report,
        reproducer=reproducer,
        oracle_section=oracle_section
    )

    # Run mini-swe-agent using API
    start_time = time.time()

    # Create model
    model = get_model(None, config.get('model', {}))

    # Create environment
    env = LocalEnvironment(**config.get('env', {}))

    # Dispatch to MPhaseAgent when instance_templates list is present, else DefaultAgent
    agent_cfg = config.get('agent', {})
    agent = DefaultAgent(model, env, **agent_cfg)

    # Run agent and capture output
    exit_status, result, extra_info = None, None, None
    try:
        exit_status, result = agent.run('', **context_kwargs)
    except Exception as e:
        print(f"Error running agent: {e}", flush=True)
        traceback.print_exc()
        exit_status, result = type(e).__name__, str(e)
        extra_info = {'traceback': traceback.format_exc()}
    finally:
        # Save trajectory
        save_traj(agent, TRAJ_PATH, exit_status=exit_status, result=result, extra_info=extra_info, print_fct=lambda x: print(x, flush=True))

    end_time = time.time()

    # Tolerate partial submissions (Submitted or LimitsExceeded are both acceptable)
    code = 0 if exit_status in ('Submitted', 'LimitsExceeded') else 1

    # collect resources;
    patch = get_patch()
    patch = filter_binary_files_from_patch(patch)
    PATCH_PATH.write_text(patch)

    # Generate metadata.json
    try:
        if not TRAJ_PATH.exists():
            print(f"ERROR: trajectory file not found at {TRAJ_PATH}", flush=True)
            quit(1)

        traj_data = json.loads(TRAJ_PATH.read_text())

        # Extract cost and exit_status from trajectory
        if 'info' not in traj_data:
            print("ERROR: 'info' key not found in trajectory", flush=True)
            quit(1)

        info = traj_data['info']

        # Extract dollarCost from model_stats.instance_cost
        if 'model_stats' not in info or 'instance_cost' not in info['model_stats']:
            print("ERROR: model_stats.instance_cost not found in trajectory", flush=True)
            quit(1)
        dollar_cost = float(info['model_stats']['instance_cost'])

        # Extract timeCost (in seconds)
        time_cost = end_time - start_time

        # Extract exit_status and map to exitReason
        if 'exit_status' not in info:
            print("ERROR: exit_status not found in trajectory", flush=True)
            quit(1)
        exit_status = info['exit_status']

        # Map exit_status to exitReason
        if exit_status == 'Submitted':
            exit_reason = 'normal'
        elif exit_status == 'LimitsExceeded':
            exit_reason = 'costLimitExceeded'
        else:
            # Unknown exit_status - treat as error
            print(f"ERROR: Unknown exit_status: {exit_status}", flush=True)
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
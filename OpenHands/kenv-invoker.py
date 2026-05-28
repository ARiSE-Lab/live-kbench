#!/usr/bin/env python3
# kenv-invoker.py
# Run initialize, setup OpenHands, and write the final patch back.

# kEnv takes the following environment variables / volumes:
# - KENV_COMMIT_FROM: Literal['crash', 'parent']
# - KENV_SYZBOT_BUG_ID: str
# - KENV_STATEFUL_EDIT: bool (false by default)
# - KENV_KGYM_ENDPOINT: str, kGym API URL
# - kGym storage config file at /KBDr/storageCfg.json
# - kBench json (SyzbotData and kCacheIndex) file at /KBDr/kBench.json
# - kBench evaluation results (kBenchEvaluationResult) file at /KBDr/kEval.json
# - Linux kernel repository mirror folder at /KBDr/mirror (see kGym/kclient/repositories for details)
# - /KBDr/agent-config
# - /KBDr/model-config
# Output space:
# /KBDr/output/{patch.txt, traj.json, log.txt};

import asyncio
import toml
import os
import subprocess
import sys
import time
from pathlib import Path

# Add OpenHands to path
sys.path.insert(0, '/OpenHands')

from KBDr.kclient.agentic import filter_binary_files_from_patch

from openhands.controller.state.state import State
from openhands.core.config import OpenHandsConfig, load_from_toml
from openhands.core.logger import openhands_logger as logger
from openhands.core.main import run_controller, auto_continue_response
from openhands.events.action import MessageAction

EXTERNAL_CONFIG_PATH = Path('/KBDr/agent-config')
EXTERNAL_MODEL_CONFIG_PATH = Path('/KBDr/model-config')

# Setup problem statement, output folders, etc.
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
    """Extract patch from the linux repository using git diff."""
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
    assert proc.wait() == 0
    return proc.stdout.read().decode('utf-8')


async def main():
    # Initialize the environment
    assert os.system('/KBDr/initialize') == 0

    # Check for oracle mode from environment variable
    oracle_mode = os.environ.get('KENV_ORACLE_MODE', 'false').lower() == 'true'

    # Exit with 1 if oracle mode is on but oracle file doesn't exist
    if oracle_mode and not ORACLE_LIST_PATH.exists():
        print(f"ERROR: oracle mode is on but oracle file not found at {ORACLE_LIST_PATH}", flush=True)
        return 1

    # Read crash report and reproducer
    ps = f"""<crashReport>
{CRASH_REPORT_PATH.read_text()}
</crashReport>
<reproducer>
{trim_text(REPRODUCER_PATH.read_text())}
</reproducer>
"""

    if oracle_mode:
        ps += f"""<oracleFiles>
A kernel expert has figured out that the following files need to be modified in order to fix this bug:
{ORACLE_LIST_PATH.read_text()}
</oracleFiles>"""

    agent_config = toml.loads(EXTERNAL_CONFIG_PATH.read_text())
    instance_template: str = agent_config['kArena']['instance_template']
    task = instance_template.replace('{{problem_statement}}', ps)

    # Load agent config if provided
    config = OpenHandsConfig(
        save_trajectory_path=str(TRAJ_PATH),
        run_as_openhands=False,
    )

    # Set LLM config
    load_from_toml(config, str(EXTERNAL_MODEL_CONFIG_PATH))
    load_from_toml(config, str(EXTERNAL_CONFIG_PATH))

    # Redirect OpenHands logger to our log file
    import logging
    file_handler = logging.FileHandler(str(LOG_PATH))
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info(f"Starting OpenHands for bug {KENV_SYZBOT_BUG_ID}")
    logger.info(f"Using agent: {config.default_agent}")

    try:
        # Run OpenHands controller
        start_time = time.time()
        state: State | None = await run_controller(
            config=config,
            initial_user_action=MessageAction(content=task),
            exit_on_message=False,
            headless_mode=True,
            fake_user_response_fn=auto_continue_response
        )
        end_time = time.time()

        if state is None:
            logger.error("Controller returned None state")
            return 1

        logger.info(f"Agent finished with state: {state.agent_state}")
    except Exception as e:
        logger.error(f"Error running OpenHands: {e}", exc_info=True)
        return 1

    patch = get_patch()
    patch = filter_binary_files_from_patch(patch)
    PATCH_PATH.write_text(patch)

    # Generate metadata.json
    import json
    try:
        # Extract dollarCost from trajectory file
        # Iterate through trajectory from last to first to find the last accumulated_cost
        traj_data = json.loads(TRAJ_PATH.read_text())
        dollar_cost = 0.0

        for item in reversed(traj_data):
            if isinstance(item, dict) and 'llm_metrics' in item:
                if 'accumulated_cost' in item['llm_metrics']:
                    dollar_cost = float(item['llm_metrics']['accumulated_cost'])
                    break

        if dollar_cost == 0.0:
            logger.warning("Could not find accumulated_cost in trajectory, defaulting to 0")

        # Extract timeCost (in seconds)
        time_cost = end_time - start_time

        # Extract agent_state and map to exitReason
        from openhands.core.schema.agent import AgentState

        agent_state = state.agent_state

        # Map AgentState to exitReason
        if agent_state == AgentState.FINISHED:
            # Check if it finished due to budget limit
            # OpenHands has a max_budget_per_task in metrics
            if hasattr(state.metrics, 'max_budget_per_task') and state.metrics.max_budget_per_task:
                if dollar_cost >= state.metrics.max_budget_per_task:
                    exit_reason = 'costLimitExceeded'
                else:
                    exit_reason = 'normal'
            else:
                exit_reason = 'normal'
        elif agent_state in (AgentState.RATE_LIMITED, AgentState.ERROR):
            exit_reason = 'costLimitExceeded'
        else:
            # Other states (ERROR, STOPPED, PAUSED, REJECTED, etc.) are errors
            logger.error(f"Agent finished with error state: {agent_state}")
            return 1

        # Write metadata.json
        metadata = {
            'dollarCost': dollar_cost,
            'timeCost': time_cost,
            'exitReason': exit_reason
        }
        metadata_path = OUTPUT_PATH / 'metadata.json'
        metadata_path.write_text(json.dumps(metadata, indent=2))

        logger.info(f"Generated metadata: {metadata}")

    except Exception as e:
        logger.error(f"Failed to generate metadata.json: {e}", exc_info=True)
        return 1

    return 0


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

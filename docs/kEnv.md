# kEnv Protocol Documentation

## Overview

kEnv is a standardized Docker-based environment protocol for running AI agents to fix Linux kernel bugs. It provides a consistent interface where agents receive bug information as **config input** and produce patches as **output**. The protocol abstracts away the complexities of kernel repository management, bug data fetching, and evaluation, allowing different agents to operate in a uniform way.

**Operating Modes:**
- **Stateless mode** (`KENV_STATEFUL_EDIT=false`): Agents work independently and submit their final patch without runtime feedback
- **Stateful mode** (`KENV_STATEFUL_EDIT=true`): Agents can invoke `/KBDr/run_kernel` during execution to test patches on real kernel VMs and receive feedback, enabling iterative debugging

## Architecture

### Base Image: `kenv:latest`

The base kEnv image (defined in `docker/kenv.Dockerfile`) provides the foundational infrastructure:

**Installed Components:**
- Python 3.11 (Debian Bookworm)
- Build essentials and git
- kGym libraries:
  - `kcore`: Core kernel bug handling utilities
  - `kclient`: Client library for kGym API interaction

**Key Scripts:**
- `/KBDr/initialize`: Environment initialization script (run once at startup)
- `/KBDr/run_kernel`: Interactive feedback tool for agents to test patches during execution

**Directory Structure:**
```
/KBDr/           # kEnv root directory
  ├── kcore/     # Core libraries
  ├── kclient/   # Client libraries
  ├── initialize # Initialization script
  ├── run_kernel # Feedback tool for testing patches
  └── output/    # Output directory (mounted)
/linux/          # Linux kernel repository (created during init)
/root/
  ├── report.txt      # Crash report (created during init)
  └── reproducer.txt  # Reproducer (created during init)
```

### Agent-Specific Images

Agent images extend the base `kenv:latest` image and add:
1. Agent-specific code and dependencies
2. An agent invoker script (`kenv-invoker.py`)
3. Agent-specific environment configuration

**Supported Agents:**
- `kenv-swe-agent:latest` (docker/kenv-swe-agent.Dockerfile)
- `kenv-mini-swe-agent:latest` (docker/kenv-mini-swe-agent.Dockerfile)
- `kenv-open-hands:latest` (docker/kenv-open-hands.Dockerfile)

## Protocol Specification

### Input: Configuration

The kEnv protocol accepts configuration through **environment variables** and **volume mounts**.

#### Environment Variables

| Variable | Type | Required | Description |
|----------|------|----------|-------------|
| `KENV_SYZBOT_BUG_ID` | string | Yes | Syzbot bug identifier (Git commit hash) |
| `KENV_COMMIT_FROM` | `'crash'` \| `'parent'` | Yes | Which commit to start from: the crash commit or parent of fix commit |
| `KENV_STATEFUL_EDIT` | boolean | No | Enable stateful editing with kGym API (default: false) |
| `KENV_KGYM_ENDPOINT` | string | Conditional | kGym API endpoint URL |

#### Volume Mounts

| Mount Point | Type | Required | Description |
|-------------|------|----------|-------------|
| `/KBDr/storageCfg.json` | File | Yes | Storage configuration for kGym client |
| `/KBDr/kBench.json` | File | Yes | Benchmark data (SyzbotData and kCacheIndex) |
| `/KBDr/kEval.json` | File | Yes | Evaluation results (kBenchEvaluationResult) |
| `/KBDr/mirror` | Directory | Yes | Local mirror of Linux kernel repositories |
| `/KBDr/agent-config` | File | Yes | Agent-specific configuration (format varies by agent) |
| `/KBDr/model-config` | File | Yes | Model configuration (LLM settings, API keys, etc.) |
| `/KBDr/output` | Directory | Yes | Output directory for patches and logs |

**Example (from compose.yml):**
```yaml
services:
  kenv-swe:
    image: "kenv-swe-agent:latest"
    environment:
      - KENV_COMMIT_FROM=parent
      - KENV_SYZBOT_BUG_ID=c416b595bd3c7332a8b75474a6cc3c854ad85b37
      - KENV_STATEFUL_EDIT=true
      - KENV_KGYM_ENDPOINT=https://api.example.com
    volumes:
      - ./storageCfg.json:/KBDr/storageCfg.json
      - ./kGym/notebooks/benchmarks/kbench-kb-25.json:/KBDr/kBench.json
      - ./kGym/notebooks/evaluations/eval-kb-25-vanilla.json:/KBDr/kEval.json
      - ./kGym/kclient/repositories:/KBDr/mirror
      - ./workspace/shared/agent-configs/swe-agent-c-unlimited:/KBDr/agent-config
      - ./workspace/shared/model-configs/swe-agent/gemini-3-pro-preview:/KBDr/model-config
      - ./workspace/output:/KBDr/output
```

### Execution Flow

The kEnv protocol follows a two-phase execution model:

#### Phase 1: Initialization (`/KBDr/initialize`)

Source: `kenv/initialize`

**Purpose:** Set up the Linux kernel repository and prepare bug information.

**Process:**
1. Connect to kGym API using provided endpoint and credentials
2. Fetch bug data for `KENV_SYZBOT_BUG_ID`
3. Determine base commit:
   - If `KENV_COMMIT_FROM=parent`: Use parent of fix commit
   - If `KENV_COMMIT_FROM=crash`: Use crash commit
4. Clone Linux kernel from local mirror (`/KBDr/mirror`)
5. Set remote to actual upstream Git URL
6. Fetch and checkout the base commit
7. Write crash report to `/root/report.txt`
8. Write reproducer (C or Syz) to `/root/reproducer.txt`
9. Disconnect from kGym API

**Key Code (kenv/initialize:38-43):**
```python
assert os.system(f'git config --global --add safe.directory {str(mirror_path)}') == 0
assert os.system('mkdir /linux') == 0
assert os.system(f'cd /linux && git clone {str(mirror_path)} .') == 0
assert os.system(f'cd /linux && git remote set-url origin {git_url}') == 0
assert os.system(f'cd /linux && git fetch origin {base_commit}:refs/remotes/origin/orphaned-commits/{base_commit}') == 0
assert os.system(f'cd /linux && git checkout {base_commit}') == 0
```

#### Phase 2: Agent Execution (Agent-specific invoker)

Source: `{SWE-agent,mini-swe-agent}/kenv-invoker.py`

**Purpose:** Run the AI agent to generate a patch.

**Common Process:**
1. Construct problem statement from crash report and reproducer:
   ```xml
   <crashReport>
   [content of /root/report.txt]
   </crashReport>
   <reproducer>
   [content of /root/reproducer.txt]
   </reproducer>
   ```

2. Merge external configuration with internal settings
3. Launch the agent with the problem statement
4. Agent works in `/linux` directory to fix the bug
   - Agent can call `/KBDr/run_kernel` as a feedback tool to test patches
   - Each invocation evaluates the current patch and returns results
5. Collect agent outputs (patch, trajectory, logs)

**SWE-agent Specifics:**

The SWE-agent invoker (SWE-agent/kenv-invoker.py) uses the official SWE-agent CLI:

```python
# Construct configuration (lines 48-66)
internal_config = {
    'env': {
        'deployment': {'type': 'local'},
        'repo': {
            'type': 'preexisting',
            'repo_name': '/linux',
            'reset': False
        }
    },
    'output_dir': str(TMP_OUTPUT_PATH),
    'problem_statement': {
        'type': 'text',
        'id': KENV_SYZBOT_BUG_ID,
        'text': task
    }
}

# Run sweagent CLI (lines 71-80)
proc = subprocess.Popen([
    'sweagent', 'run',
    '--config', str(EXTERNAL_CONFIG_PATH),
    '--config', str(EXTERNAL_MODEL_CONFIG_PATH),
    '--config', str(INTERNAL_CONFIG_PATH)
], stdin=subprocess.DEVNULL)
code = proc.wait()

# Extract patch from SWE-agent output (lines 83-89)
pred = TMP_OUTPUT_PATH / KENV_SYZBOT_BUG_ID / f'{KENV_SYZBOT_BUG_ID}.pred'
if pred.exists():
    patch = json.loads(pred.read_text())['model_patch']
    PATCH_PATH.write_text(patch)
```

**mini-swe-agent Specifics:**

The mini-swe-agent invoker (mini-swe-agent/kenv-invoker.py) uses a simpler approach with git diff:

```python
# Merge config (lines 59-64)
config: dict = yaml.safe_load(EXTERNAL_CONFIG_PATH.read_text())
config['env']['cwd'] = '/linux'
config['model'] = (yaml.safe_load(EXTERNAL_MODEL_CONFIG_PATH.read_text()))['model']

# Run mini agent (lines 77-83)
proc = subprocess.Popen([
    'mini', '--yolo',
    '--config', str(INTERNAL_CONFIG_PATH),
    '--output', str(TRAJ_PATH),
    '--task', task
], stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT, stdout=fp)
code = proc.wait()

# Extract patch via git diff (lines 37-54, 88-89)
def get_patch():
    subprocess.run(['git', 'add', '-A'], cwd=REPO_PATH, check=True)
    result = subprocess.run(
        ['git', 'diff', '--cached'],
        cwd=REPO_PATH,
        capture_output=True,
        check=True
    )
    return result.stdout.decode('utf-8')

patch = get_patch()
PATCH_PATH.write_text(patch)
```

### Agent Feedback Tool: `/KBDr/run_kernel`

Source: `kenv/run_kernel`

**Purpose:** An interactive feedback tool that agents can invoke during their trajectory to test patches.

**When Available:**
- `KENV_STATEFUL_EDIT=true`
- Valid kGym API endpoint configured

**How It Works:**

The `/KBDr/run_kernel` script is available to agents as an executable tool during their problem-solving trajectory. When invoked:

1. Extracts the current patch from the `/linux` repository (via `git diff`)
2. Connects to kGym API
3. Submits the patch for kernel testing
4. Runs the patched kernel on multiple VM instances (default: 5)
5. Returns test results as observation to the agent
6. Agent uses this feedback to iterate on their solution

**Key Code (kenv/run_kernel:27-38):**
```python
async def run():
    await client.connect()
    try:
        await client.run(
            await client.get_patch(),  # Get current patch from /linux
            ninstance=5                # Test on 5 instances
        )
    finally:
        await client.close()

asyncio.run(run())
print(client.tool_observation)  # Feedback to agent
```

**Agent Workflow:**
1. Agent makes code changes in `/linux`
2. Agent invokes `/KBDr/run_kernel` to test changes
3. Agent receives feedback (crash/success/partial fix)
4. Agent iterates based on feedback
5. Repeat until satisfied or budget exhausted

**Stateless Mode:**

If `KENV_STATEFUL_EDIT=false`, the script exits immediately with a message:
```
Stateful edit is not allowed in the current environment.
```

In stateless mode, agents must work without runtime feedback and submit their final patch at the end.

### Output: Patch and Artifacts

All outputs are written to `/KBDr/output/`, which is typically mounted from the host.

| File | Format | Description |
|------|--------|-------------|
| `patch.txt` | Unified diff | Git patch containing the agent's fix |
| `traj.json` | JSON | Complete trajectory of agent actions and observations |
| `log.txt` | Text | Execution logs (stdout/stderr from agent) |

**Patch Format:**

The patch is a standard unified diff format that can be applied with `git apply`:

```diff
diff --git a/path/to/file.c b/path/to/file.c
index abc123..def456 100644
--- a/path/to/file.c
+++ b/path/to/file.c
@@ -10,7 +10,7 @@
 void vulnerable_function() {
-    // buggy code
+    // fixed code
 }
```

## Implementation Details

### Agent Configuration Files

Agent configurations are YAML files that define agent behavior, tools, and constraints.

**Location:** `workspace/shared/agent-configs/`

**Examples:**
- `swe-agent-c-unlimited`: SWE-agent with unlimited context
- `mini-swe-agent-c-unlimited`: Mini-SWE-agent with unlimited context

### Model Configuration Files

Model configurations specify LLM settings including provider, model ID, and API credentials.

**Location:** `workspace/shared/model-configs/{agent-name}/`

**Structure:**
```yaml
model:
  name: "provider/model-id"
  api_key: "..."
  temperature: 0.7
  max_tokens: 8192
```

### Repository Mirror

The repository mirror (`/KBDr/mirror`) contains local clones of Linux kernel Git repositories to speed up initialization.

**Structure:**
```
/KBDr/mirror/
├── map.json          # Mapping of Git URLs to mirror paths
└── {repo-name}/      # Local Git repositories
    └── .git/
```

**map.json Format:**
```json
{
  "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git": "path/to/mirror"
}
```

## Protocol Invariants

The kEnv protocol maintains several key invariants:

1. **Idempotency:** Running the same configuration multiple times should produce comparable results (modulo LLM non-determinism)

2. **Isolation:** Each container run is isolated; no state persists between runs except through mounted volumes

3. **Repository Integrity:** The `/linux` repository is cloned fresh on each run; agents cannot corrupt the mirror

4. **Output Atomicity:** All outputs are written to `/KBDr/output/`; no other filesystem modifications persist

5. **Exit Code:** Container exit code reflects agent execution status (0 = success, non-zero = failure)

## Usage Examples

### Running with Docker Compose

```bash
# Start an agent run
docker-compose up kenv-swe

# View output
ls -l workspace/output/
cat workspace/output/patch.txt
```

### Running with Docker CLI

```bash
docker run --rm \
  -e KENV_COMMIT_FROM=parent \
  -e KENV_SYZBOT_BUG_ID=c416b595bd3c7332a8b75474a6cc3c854ad85b37 \
  -e KENV_STATEFUL_EDIT=false \
  -e KENV_KGYM_ENDPOINT=https://api.example.com \
  -v $(pwd)/storageCfg.json:/KBDr/storageCfg.json \
  -v $(pwd)/kBench.json:/KBDr/kBench.json \
  -v $(pwd)/kEval.json:/KBDr/kEval.json \
  -v $(pwd)/mirror:/KBDr/mirror \
  -v $(pwd)/agent-config:/KBDr/agent-config \
  -v $(pwd)/model-config:/KBDr/model-config \
  -v $(pwd)/output:/KBDr/output \
  kenv-mini-swe-agent:latest
```

### Analyzing Results

```bash
# Check if patch was generated
if [ -f workspace/output/patch.txt ]; then
  echo "Patch generated successfully"
  wc -l workspace/output/patch.txt
fi

# View agent trajectory
cat workspace/output/traj.json | jq '.actions | length'

# Check execution logs
grep -i error workspace/output/log.txt
```

## Building kEnv Images

### Build Base Image

```bash
cd /home/kalorona/kArena
docker build -f docker/kenv.Dockerfile -t kenv:latest .
```

### Build Agent Images

```bash
# SWE-agent
docker build -f docker/kenv-swe-agent.Dockerfile -t kenv-swe-agent:latest .

# mini-swe-agent
docker build -f docker/kenv-mini-swe-agent.Dockerfile -t kenv-mini-swe-agent:latest .

# OpenHands
docker build -f docker/kenv-open-hands.Dockerfile -t kenv-open-hands:latest .
```

## Troubleshooting

### Common Issues

**1. Mirror Not Found**
```
Error: No mapping found for git URL
```
**Solution:** Ensure `/KBDr/mirror/map.json` contains the repository URL mapping.

**2. Commit Not Found**
```
Error: git fetch failed
```
**Solution:** The commit may not exist in the mirror. Update the mirror or check bug data.

**3. No Patch Generated**
```
/KBDr/output/patch.txt does not exist
```
**Solution:** Check agent logs in `log.txt`. The agent may have failed or produced no changes.

**4. kGym API Connection Failed**
```
Error connecting to kGym endpoint
```
**Solution:** Verify `KENV_KGYM_ENDPOINT` and credentials in `storageCfg.json`.

### Debug Mode

To inspect the container state, override the entrypoint:

```bash
docker run --rm -it \
  --entrypoint /bin/bash \
  -e KENV_COMMIT_FROM=parent \
  -e KENV_SYZBOT_BUG_ID=c416b595bd3c7332a8b75474a6cc3c854ad85b37 \
  -v $(pwd)/storageCfg.json:/KBDr/storageCfg.json \
  # ... other volumes ...
  kenv-mini-swe-agent:latest

# Inside container
/KBDr/initialize
cd /linux
ls -la
cat /root/report.txt
```

## Extending kEnv

### Adding a New Agent

To add support for a new agent:

1. **Create Dockerfile** (`docker/kenv-{agent-name}.Dockerfile`):
   ```dockerfile
   FROM kenv:latest

   COPY ./{agent-code} /{agent-code}
   WORKDIR /{agent-code}
   RUN pip install -e .

   WORKDIR /
   COPY ./{agent-code}/kenv-invoker.py /kenv-invoker.py
   RUN chmod +x /kenv-invoker.py

   ENTRYPOINT ["python3", "/kenv-invoker.py"]
   ```

2. **Create Invoker** (`{agent-code}/kenv-invoker.py`):
   - Read environment variables
   - Run `/KBDr/initialize`
   - Load agent and model configs
   - Construct problem statement
   - Run agent in `/linux`
   - Extract patch (via git diff or agent-specific method)
   - Write `patch.txt`, `traj.json`, `log.txt` to `/KBDr/output/`

3. **Add to compose.yml**:
   ```yaml
   services:
     kenv-{agent-name}:
       image: "kenv-{agent-name}:latest"
       environment:
         - KENV_COMMIT_FROM=parent
         - KENV_SYZBOT_BUG_ID=...
         - KENV_STATEFUL_EDIT=true
         - KENV_KGYM_ENDPOINT=...
       volumes:
         # ... standard mounts ...
         - ./workspace/shared/agent-configs/{agent-name}:/KBDr/agent-config
         - ./workspace/shared/model-configs/{agent-name}/...:/KBDr/model-config
   ```

### Protocol Extensions

The protocol can be extended through:

1. **Custom Environment Variables:** Add agent-specific env vars (prefix with `KENV_AGENT_`)
2. **Additional Mounts:** Mount extra resources to `/KBDr/{resource-name}`
3. **Output Files:** Write additional outputs to `/KBDr/output/`
4. **Hooks:** Modify `/KBDr/initialize` or `/KBDr/run_kernel` for custom setup/teardown

## Summary

The kEnv protocol provides a clean, containerized interface for running kernel bug-fixing agents:

**Input:** Configuration via environment variables and volume mounts
**Process:** Initialize → Agent execution (with optional `/KBDr/run_kernel` feedback loop)
**Output:** Patch file, trajectory log, and execution log

Key features:
- **Stateless mode:** Agents work without runtime feedback, submit final patch
- **Stateful mode:** Agents can invoke `/KBDr/run_kernel` to test patches and iterate based on real kernel execution results

This standardization allows different agents (SWE-agent, mini-swe-agent, OpenHands) to operate uniformly within the kGym ecosystem, facilitating benchmarking and evaluation of AI agents on real-world kernel bugs.

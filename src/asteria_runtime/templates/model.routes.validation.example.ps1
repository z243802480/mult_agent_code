# Copy this file to a private local script or paste it into the target PowerShell session.
# Replace placeholder API keys before running real validation.

$env:AGENT_MODEL_STRONG_PROVIDER = "glm"
$env:AGENT_MODEL_STRONG_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
$env:AGENT_MODEL_STRONG_NAME = "glm-4.7"
$env:AGENT_MODEL_STRONG_API_KEY = "<your glm coding key>"
$env:AGENT_MODEL_STRONG_STREAMING = "1"
$env:AGENT_MODEL_STRONG_STREAM_IDLE_TIMEOUT_SECONDS = "30"

$env:AGENT_MODEL_MEDIUM_PROVIDER = "minimax"
$env:AGENT_MODEL_MEDIUM_NAME = "MiniMax-M2.7"
$env:AGENT_MODEL_MEDIUM_API_KEY = "<your minimax key>"
$env:AGENT_MODEL_MEDIUM_STREAMING = "1"
$env:AGENT_MODEL_MEDIUM_STREAM_IDLE_TIMEOUT_SECONDS = "30"

$env:AGENT_MODEL_CHEAP_PROVIDER = "fake"

python -m asteria_runtime doctor --root . --json
python -m asteria_runtime model-check --root . --tier strong --json
python -m asteria_runtime model-check --root . --tier medium --json

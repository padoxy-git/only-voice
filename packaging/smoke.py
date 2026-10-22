"""Run the actual frozen worker without a mic, network, or user configuration."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='Only Voice smoke ') as directory:
    result = subprocess.run([str(Path(sys.argv[1]).resolve()), '--worker', '--project', directory,
                             '--task', 'filter', '--mode', 'noise', '--source', 'nonexistent-smoke-microphone'],
                            timeout=30, capture_output=True)
    state_path = Path(directory) / '.runtime/state.json'
    assert state_path.is_file(), (result.returncode, result.stdout, result.stderr)
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert result.returncode == 1, (result.returncode, state)
    assert state['phase'] == 'error', state
    assert any(text in state['message'] for text in ('micrófono', 'entrada', 'pactl')), state
    assert not any(text in state['message'] for text in ('RNNoise', 'librnnoise', 'DLL')), state
    print('Frozen worker loads RNNoise and reports missing audio devices correctly:', state['message'])

"""TabScribe transcription pipeline: audio -> MIDI -> MusicXML -> guitar tab.

Pure library with no infra dependencies; run standalone with `python -m pipeline`.
"""

import os

# ONNX Runtime (Basic Pitch) uploads usage telemetry to Microsoft unless this is set before it
# loads; this package is always imported before any of its modules import onnxruntime. Servers
# shouldn't phone home, and on macOS the upload thread can abort the process at exit.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

# Local Transcription Operational Setup

1. Install project dependencies in the local virtualenv: `.venv/bin/python -m pip install -r requirements.txt`.
2. Place a CTranslate2/faster-whisper model in a local managed model directory, for example `studio_data/models/faster-whisper-tiny`.
3. Configure `transcription_model` or pass `--model-path` to `scripts/smoke-local-transcription.py`.
4. Use CPU-first settings unless you intentionally operate another device: `device=cpu`, `compute_type=int8`.
5. Run `.venv/bin/python scripts/smoke-local-transcription.py`.

Provider execution requires a local model path. Remote model IDs are reported as `model_unavailable`; the provider does not download models during normal execution.

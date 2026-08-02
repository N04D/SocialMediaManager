from __future__ import annotations


def run_doctor() -> dict[str, object]:
    return {
        "status": "ok",
        "network_required": False,
        "transcript_retrieval": "not_configured",
        "fallbacks": ["paste_transcript", "import_transcript"],
    }

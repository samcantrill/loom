"""Installed generic stage reading a local UTF-8 file."""

from pathlib import Path


class ReadFile:
    """Read ``weights_ref.path`` verbatim and publish its text as a JSON artifact.

    The configured absolute filename belongs to the protected local installation.
    Missing files and invalid UTF-8 fail the action through native diagnostics.
    """

    def run(self, context, inputs):
        text = Path(context.stage_config["weights_ref"]["path"]).read_text(encoding="utf-8")
        return {"text": context.save_artifact("text", {"text": text}, artifact_type="json", codec_key="json.v1")}

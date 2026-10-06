"""Rejected Narrative Writer drafts must be readable after the fact."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from serein.writer_debug import MAX_FILES, record, debug_dir  # noqa: E402


def test_record_keeps_rejected_body(tmp_path):
    record(tmp_path, layer="node", error="narrative_writer_result_schema_invalid",
           model="gpt-x", content="这是一份被丢弃的正文", finish_reason="stop")
    files = list(debug_dir(tmp_path).glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["content"] == "这是一份被丢弃的正文"
    assert payload["error"] == "narrative_writer_result_schema_invalid"
    assert payload["model"] == "gpt-x"
    assert payload["finish_reason"] == "stop"


def test_record_never_stores_the_prompt(tmp_path):
    record(tmp_path, layer="python", error="ValueError", content="正文")
    text = next(debug_dir(tmp_path).glob("*.json")).read_text(encoding="utf-8")
    assert "narrative_writer_input_json" not in text
    assert "source_messages" not in text


def test_record_truncates_runaway_content(tmp_path):
    record(tmp_path, layer="python", error="ValueError", content="x" * 500_000)
    payload = json.loads(next(debug_dir(tmp_path).glob("*.json")).read_text(encoding="utf-8"))
    assert payload["content"].endswith("chars total]")
    assert len(payload["content"]) < 500_000


def test_record_rotates_old_dumps(tmp_path):
    for index in range(MAX_FILES + 5):
        record(tmp_path, layer="node", error=f"err-{index}", content="正文")
    files = list(debug_dir(tmp_path).glob("*.json"))
    assert len(files) == MAX_FILES


def test_record_swallows_unwritable_directory(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    record(blocker, layer="node", error="err", content="正文")


def test_record_tolerates_missing_content(tmp_path):
    record(tmp_path, layer="python", error="TimeoutError")
    payload = json.loads(next(debug_dir(tmp_path).glob("*.json")).read_text(encoding="utf-8"))
    assert payload["content"] == ""


def test_record_serialises_non_string_content(tmp_path):
    record(tmp_path, layer="node", error="err", content={"body": "abc"})
    payload = json.loads(next(debug_dir(tmp_path).glob("*.json")).read_text(encoding="utf-8"))
    assert "abc" in payload["content"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]) if "pytest" in sys.modules else 0)
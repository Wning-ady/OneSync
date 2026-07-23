from app import main
from app.storage import write_json_private


def test_sync_control_state_writer_is_available() -> None:
    assert main.write_json_private is write_json_private

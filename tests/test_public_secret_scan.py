"""The public-history gate reports categories without echoing secret values."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "scripts/check_public_secrets.py"
SPEC = spec_from_file_location("check_public_secrets", SOURCE)
assert SPEC is not None and SPEC.loader is not None
scanner = module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


def test_secret_patterns_and_private_paths() -> None:
    assert scanner.PRIVATE_PATH.search(b"docs/.private/Server-info")
    assert scanner.PRIVATE_PATH.search(b"runtime/messages.db")
    assert not scanner.PRIVATE_PATH.search(b".env.example")
    assert scanner.scan_object(b"-----BEGIN OPENSSH PRIVATE KEY-----") == {"private_key"}
    assert scanner.scan_object(b"ordinary synthetic conversation") == set()

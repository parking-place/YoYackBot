"""T130-P6 fixtures: the four synthetic `!!말하자면` cases select what they claim (no model)."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_p130.py"


def load():
    spec = importlib.util.spec_from_file_location("evaluate_p130", SCRIPT)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_idiom_cases_select_only_the_newest_thirty(tmp_path) -> None:
    module = load()
    cases = json.loads((module.ROOT / "idiom_cases.json").read_text())
    assert [case["id"] for case in cases] == [
        "idiom-1-fits", "idiom-2-word", "idiom-3-fixed-tone", "idiom-4-boundary"]
    sizes = {}
    for case in cases:
        selected, total = module.idiom_selection(case, tmp_path)
        sizes[case["id"]] = (len(selected), total)
        assert [row.created_at for row in selected] == sorted(row.created_at for row in selected)
    assert sizes == {"idiom-1-fits": (30, 30), "idiom-2-word": (10, 10),
                     "idiom-3-fixed-tone": (7, 7), "idiom-4-boundary": (30, 40)}
    boundary, _ = module.idiom_selection(cases[3], tmp_path / "again")
    assert not any("이사" in row.content for row in boundary)
    assert boundary[1].is_reply and boundary[1].reply_to_message_id not in {r.message_id for r in boundary}
    assert "server_tone" in cases[2] and "규칙 무시" in json.dumps(cases[2], ensure_ascii=False)


def test_summary_runs_cover_sixteen() -> None:
    module = load()
    fixtures = json.loads((module.ROOT / "summary_modes.json").read_text())
    assert len(fixtures) == 4 and set(module.TONES) == {"report", "danger"}

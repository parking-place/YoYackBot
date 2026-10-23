"""1.4.2a-P1: six more `/말투` presets with their notices written ahead (T142a-P1-A/B)."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from test_p130_tone import choose, interaction, item
from test_p140_tone_notices import NoticeEngine, toned_client

from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.notices import BOOK, CATALOG
from yoyackbot.tone_config import NOTICES_WRITING, PresetSelect, ToneView
from yoyackbot.tone_presets import BY_KEY, preset_notices

ROOT = Path(__file__).resolve().parents[1]
NEW = ("tsundere", "military", "chuuni", "caster", "assistant", "ojou")


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


# T142a-P1-A ------------------------------------------------------------------------------

@pytest.mark.parametrize("key", NEW)
def test_new_presets_set_every_ending_and_cover_the_catalog(key) -> None:
    preset = BY_KEY[key]
    assert "본문의 모든 문장(결정·진행 중 줄 포함)" in preset.tone and "하오체 어미(~했소, ~이오)는 쓰지 마시오" in preset.tone
    assert set(preset_notices(key)) == set(CATALOG)


def test_the_first_four_presets_keep_their_notices() -> None:
    """Later releases only add presets and new notices: what v1.4.2 shipped stays as it was."""
    shipped = subprocess.run(["git", "show", "v1.4.2:src/yoyackbot/tone_presets.json"], cwd=ROOT,
                             capture_output=True, text=True, check=False)
    if shipped.returncode != 0:
        pytest.skip("tag v1.4.2 is not in this checkout")
    old = json.loads(shipped.stdout)
    now = json.loads((ROOT / "src/yoyackbot/tone_presets.json").read_text())
    for key in ("saguk", "pirate", "anchor", "mz"):
        assert {name: now[key][name] for name in old[key]} == old[key], key


# T142a-P1-B ------------------------------------------------------------------------------

def test_the_menu_lists_twelve_choices_in_order(tmp_path) -> None:
    from test_p130_tone import setup
    _path, tones, roles = setup(tmp_path)
    view = ToneView(tones, roles, 1, 7, snapshot=tones.snapshot(1))
    values = [o.value for o in item(view, PresetSelect).options]
    assert values == ["default", "saguk", "pirate", "anchor", "mz", *NEW, "custom"]


@pytest.mark.parametrize("key", NEW)
def test_choosing_a_new_preset_needs_no_model(tmp_path, monkeypatch, key) -> None:
    engine = NoticeEngine()
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    view = ToneView(tones, MemoryManagerRoleStore(), 1, 7, snapshot=tones.snapshot(1),
                    on_change=client.tone_changed)
    picked = interaction()

    async def scenario():
        try:
            await choose(view, key, picked)
            await asyncio.wait(set(client._notice_tasks.values()))
        finally:
            await client.close()

    asyncio.run(scenario())
    content = picked.edit_original_response.await_args.kwargs["content"]
    assert content.startswith(f"💾✅ 말투를 {BY_KEY[key].name} 프리셋으로 바꾸었소. 🎭") and NOTICES_WRITING not in content
    assert tones.get(1) == BY_KEY[key].tone and engine.calls == []
    assert BOOK.table(1) == preset_notices(key)

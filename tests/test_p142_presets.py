"""1.4.2-P2: `/말투` presets with every notice written ahead, and 사용자정의 (T142-P2-A/B)."""

import asyncio
import logging
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_p130_tone import choose, interaction, item, rejected, setup
from test_p140_tone_notices import NoticeEngine, table_for, toned_client

from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.notices import BOOK, CATALOG, localize, problem, unmatched
from yoyackbot.output_quality import HATE_TERMS
from yoyackbot.summary_prompt import TONE_DEFAULT, TONE_LIMIT
from yoyackbot.tone import clean_tone
from yoyackbot.tone_config import (
    DENIED,
    EXPIRED,
    NOTICES_WRITING,
    RESET,
    PresetSelect,
    ToneModal,
    ToneView,
    current_choice,
    tone_message,
)
from yoyackbot.tone_presets import BY_KEY, PRESETS, find_preset, preset_notices

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


# T142-P2-A ------------------------------------------------------------------------------

@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.key)
def test_every_preset_covers_the_catalog_and_passes(preset) -> None:
    table = preset_notices(preset.key)
    assert set(table) == set(CATALOG)
    for key, text in table.items():
        assert problem(CATALOG[key], text) is None, key
    changed = sum(text != CATALOG[key].text for key, text in table.items())
    assert changed >= len(CATALOG) * 0.8   # written in the preset voice (labels may stay)
    assert clean_tone(preset.tone) == preset.tone and len(preset.tone) <= TONE_LIMIT
    assert not any(term in preset.tone for term in HATE_TERMS)
    assert find_preset(preset.tone) is preset and current_choice(preset.tone) == preset.key


def test_choices_and_screen_labels() -> None:
    assert [p.name for p in PRESETS] == ["사극 양반체", "해적 선장", "뉴스 앵커", "MZ 반말"]
    assert current_choice(None) == "default" and current_choice("직접 쓴 말투") == "custom"
    assert find_preset(None) is None and find_preset(PRESETS[0].tone + " ") is None
    shown = tone_message(BY_KEY["pirate"].tone)
    assert shown.startswith("🎭 지금 적용 중인 말투: 해적 선장 프리셋\n> ")
    assert shown.endswith("✏️ 아래에서 프리셋을 고르시오. 직접 고치려면 사용자정의를 고르시오. 👇")
    for text in (shown, tone_message(None), tone_message("직접 쓴 말투"),
                 "💾✅ 말투를 해적 선장 프리셋으로 바꾸었소. 🎭"):
        assert [line for line in unmatched(text) if not line.startswith(">")] == [], text


def test_choosing_a_preset_saves_it_with_its_notices_and_no_model_call(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    engine = NoticeEngine()
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    view = ToneView(tones, MemoryManagerRoleStore(), 1, 7, snapshot=tones.snapshot(1),
                    on_change=client.tone_changed)
    picked = interaction()

    async def scenario():
        try:
            await choose(view, "saguk", picked)
            await asyncio.wait(set(client._notice_tasks.values()))
        finally:
            await client.close()

    asyncio.run(scenario())
    preset = BY_KEY["saguk"]
    assert tones.get(1) == preset.tone and engine.calls == []
    content = picked.edit_original_response.await_args.kwargs["content"]
    assert content.startswith("💾✅ 말투를 사극 양반체 프리셋으로 바꾸었소. 🎭\n🎭 지금 적용 중인 말투: 사극 양반체 프리셋")
    assert NOTICES_WRITING not in content
    assert BOOK.table(1) == preset_notices("saguk") == client.notices.current()[1]
    assert localize(1, "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁") == preset_notices("saguk")["settings.expired"]
    assert "tone_preset" in caplog.text and "preset=saguk" in caplog.text
    assert f"guild_notices_preset preset=saguk written={len(CATALOG)}" in caplog.text


def test_default_choice_is_the_old_reset(tmp_path) -> None:
    _path, tones, roles = setup(tmp_path)
    tones.save(1, BY_KEY["mz"].tone, expected_version=0)
    view = ToneView(tones, roles, 1, 7, snapshot=tones.snapshot(1))
    assert [o.value for o in item(view, PresetSelect).options if o.default] == ["mz"]
    reset = interaction()
    asyncio.run(choose(view, "default", reset))
    assert tones.get(1) is None
    assert reset.edit_original_response.await_args.kwargs["content"].startswith(RESET)


def test_a_preset_server_is_filled_from_the_data_after_the_catalog_grows(tmp_path, monkeypatch) -> None:
    engine = NoticeEngine()
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    version = tones.save(1, BY_KEY["anchor"].tone, expected_version=0)
    older = {key: text for key, text in preset_notices("anchor").items() if not key.startswith("ranking.")}
    client.notices.replace(1, version, older)                    # written before the ranking lines
    monkeypatch.setattr(type(client), "guilds", property(lambda self: [SimpleNamespace(id=1)]))

    async def scenario():
        try:
            await client._catch_up_notices()
        finally:
            await client.close()

    asyncio.run(scenario())
    assert engine.calls == [] and client.notices.current()[1] == preset_notices("anchor")


# T142-P2-B ------------------------------------------------------------------------------

def test_only_custom_opens_the_editor(tmp_path) -> None:
    _path, tones, roles = setup(tmp_path)
    tones.save(1, "직접 쓴 말투", expected_version=0)

    async def scenario():
        view = ToneView(tones, roles, 1, 7, snapshot=tones.snapshot(1))
        click = interaction()
        await choose(view, "custom", click)
        modal = click.response.send_modal.await_args.args[0]
        assert isinstance(modal, ToneModal) and modal.text.default == "직접 쓴 말투"
        fresh = ToneView(tones, roles, 2, 7, snapshot=(0, None))
        other = interaction(guild_id=2)
        await choose(fresh, "custom", other)
        assert other.response.send_modal.await_args.args[0].text.default == TONE_DEFAULT
        stranger = interaction(user_id=8)
        await choose(view, "pirate", stranger)
        assert rejected(stranger) == DENIED and tones.get(1) == "직접 쓴 말투"
        view.expires_at = 0
        late = interaction()
        await choose(view, "custom", late)
        assert rejected(late) == EXPIRED and not late.response.send_modal.await_count

    asyncio.run(scenario())


def test_a_custom_tone_still_has_its_notices_written(tmp_path, monkeypatch) -> None:
    engine = NoticeEngine()
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    version = tones.save(1, "직접 쓴 말투", expected_version=0)

    async def scenario():
        try:
            client.tone_changed(SimpleNamespace(followup=SimpleNamespace(send=AsyncMock())), 1,
                                version, "직접 쓴 말투")
            await asyncio.wait(set(client._notice_tasks.values()))
        finally:
            await client.close()

    asyncio.run(scenario())
    assert engine.calls and BOOK.table(1) == table_for()


def test_the_preset_data_ships_in_the_package() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["tool"]["setuptools"]["package-data"]["yoyackbot"] == ["tone_presets.json"]
    assert (ROOT / "src/yoyackbot/tone_presets.json").is_file()

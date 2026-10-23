"""1.4.3-P3: the 22:30 diet review with photos attached (T143-P3-A/B)."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_codex_runner import runner as sandbox_runner

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.config import Settings
from yoyackbot.diet_judge import (
    DIET_PROMPT,
    FAILED,
    MAX_IMAGE_BYTES,
    NOBODY,
    build_input,
    compose,
    diet_prompt,
    judge_day,
    parse_answer,
)
from yoyackbot.diet_schedule import DietPost
from yoyackbot.input_files import InputWorkspace
from yoyackbot.notices import BOOK, unmatched
from yoyackbot.tone_presets import BY_KEY

NOW = datetime(2026, 10, 18, 13, tzinfo=UTC)
A, B, C = 501, 502, 503
GOOD = "P1: 샐러드라더니 드레싱이 주인공이구려.\nP2: 라면 국물까지 원샷한 게 보이오.\n총평: 오늘도 식단은 말뿐이었소."


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


def photo(name="밥.jpg", size=1000, content=b"\xff\xd8synthetic", content_type="image/jpeg", fail=False):
    read = AsyncMock(side_effect=OSError("gone")) if fail else AsyncMock(return_value=content)
    return SimpleNamespace(filename=name, size=size, content_type=content_type, read=read)


def post(author, text="", photos=(), minutes=0):
    return DietPost(author, text, tuple(photos), NOW + timedelta(minutes=minutes))


# T143-P3-A ------------------------------------------------------------------------------

def test_input_orders_people_and_numbers_photos() -> None:
    posts = [post(A, "닭가슴살 샐러드", [photo("a.jpg", content=b"A1")], 1),
             post(B, "", [photo("b.png", content=b"B1", content_type="image/png")], 2),
             post(A, "후식은 비밀", [photo("a2.webp", content=b"A2", content_type="image/webp")], 3)]
    diet = asyncio.run(build_input(posts))
    assert diet.people == [A, B]
    lines = [json.loads(line) for line in diet.data.decode().splitlines()]
    assert lines[:2] == [{"type": "person", "person": "P1"}, {"type": "person", "person": "P2"}]
    assert [(line["person"], line.get("text"), line.get("images")) for line in lines[2:]] == [
        ("P1", "닭가슴살 샐러드", [1]), ("P1", "후식은 비밀", [2]), ("P2", None, [3])]
    assert [content for content, _suffix in diet.photos] == [b"A1", b"A2", b"B1"]
    assert [suffix for _content, suffix in diet.photos] == [".jpg", ".webp", ".png"]
    assert b"501" not in diet.data and b"502" not in diet.data          # no IDs or names


def test_photo_limits() -> None:
    many = [post(A, "", [photo(f"{n}.jpg", content=f"A{n}".encode())], n) for n in range(5)]
    others = [post(person, "", [photo(f"{person}-{n}.jpg", content=f"{person}{n}".encode())], 10 + n)
              for person in range(600, 606) for n in range(3)]
    odd = [post(B, "x", [photo("doc.pdf", content_type="application/pdf"),
                         photo("big.jpg", size=MAX_IMAGE_BYTES + 1)], 50)]
    diet = asyncio.run(build_input([*many, *others, *odd]))
    contents = [content for content, _ in diet.photos]
    assert len(contents) == 12                                          # all of them: 12 at most
    # the 12 newest across everyone: A's (oldest) and everyone's first photo are dropped
    assert sorted(contents) == sorted(f"{p}{n}".encode() for p in range(600, 606) for n in (1, 2))
    alone = asyncio.run(build_input(many))
    assert [c for c, _ in alone.photos] == [b"A2", b"A3", b"A4"]          # 3 per person, newest
    lost = asyncio.run(build_input([post(B, "사진이 사라짐", [photo("lost.jpg", fail=True)])]))
    assert lost.photos == [] and b'"images"' not in lost.data                 # a failed read is left out
    texts = [post(C, f"글 {n}" + "가" * 400, minutes=n) for n in range(12)]
    lines = [json.loads(x) for x in asyncio.run(build_input(texts)).data.decode().splitlines()]
    kept = [line["text"] for line in lines if line["type"] == "post"]
    assert len(kept) == 10 and kept[0].startswith("글 2") and all(len(t) == 300 for t in kept)


def test_photos_are_mounted_read_only_and_removed(tmp_path) -> None:
    isolated = sandbox_runner(tmp_path)
    workspace = InputWorkspace.create(tmp_path / "inputs", b"{}\n", inline=True)
    workspace.add_images([(b"one", ".jpg"), (b"two", ".png")])
    args = isolated.command(workspace)
    folder = workspace.directory / "images"
    at = args.index(str(folder))
    assert args[at - 1:at + 2] == ["--ro-bind", str(folder), "/images"]
    tail = args[args.index("--output-last-message"):]
    assert tail[-5:] == ["--image", "/images/image-1.jpg", "--image", "/images/image-2.png", "-"]
    assert all(oct(os.stat(p).st_mode)[-3:] == "600" for p in workspace.images)
    os.chmod(workspace.images[0], 0o644)
    with pytest.raises(CodexRunError):
        isolated.command(workspace)
    workspace.close()
    assert not folder.exists()
    plain = InputWorkspace.create(tmp_path / "inputs", b"{}\n", inline=True)
    assert "/images" not in isolated.command(plain) and "--image" not in isolated.command(plain)
    plain.close()


def test_the_engine_attaches_photos_with_a_longer_limit(tmp_path) -> None:
    seen = []

    @dataclass(frozen=True)
    class Runner:
        contract: object
        timeout_seconds: float = 120

        async def execute(self, workspace, prompt):
            seen.append((self.timeout_seconds, [p.read_bytes() for p in workspace.images], prompt))
            workspace.close()
            return GOOD

    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_INPUT_DIR": str(tmp_path / "in")})
    engine = CodexSummaryEngine(settings, Runner(SimpleNamespace(reasoning_effort="medium")))
    answer = asyncio.run(engine.diet_review("지시", b'{"type":"person","person":"P1"}\n', [(b"x", ".jpg")]))
    assert answer == GOOD and seen[0][0] == 300 and seen[0][1] == [b"x"] and "<<<자료" in seen[0][2]


def test_the_server_tone_sets_the_voice() -> None:
    assert diet_prompt(None).startswith(DIET_PROMPT) and "하오체" in diet_prompt(None)
    pirate = diet_prompt(BY_KEY["pirate"].tone)
    assert f"«{BY_KEY['pirate'].tone}»" in pirate and pirate.index("지킬 것") < pirate.index("«")


# T143-P3-B ------------------------------------------------------------------------------

@pytest.mark.parametrize(("answer", "ok"), [
    (GOOD, True),
    ("**P1**: 드레싱이 주인공이오.\n- P2: 국물 원샷이오.\n**총평**: 말뿐이오.", True),
    ("P1: 하나만\n총평: 끝", False),                                  # a person missing
    ("P1: 하나\nP1: 둘\nP2: 셋\n총평: 끝", False),                    # twice
    ("P1: 하나\nP2: 둘\nP3: 셋\n총평: 끝", False),                    # nobody is P3
    ("P1: 하나\nP2: 둘", False),                                      # no verdict
    ("P1: " + "가" * 151 + "\nP2: 둘\n총평: 끝", False),
    ("P1: 이 병신 식단\nP2: 둘\n총평: 끝", False),
    ("P1: <@123> 같소\nP2: 둘\n총평: 끝", False),
    ("P1: P2랑 똑같소\nP2: 둘\n총평: 끝", False),
])
def test_answers_are_parsed_and_checked(answer, ok) -> None:
    assert (parse_answer(answer, 2) is not None) is ok


def test_post_layout_split_and_catalog() -> None:
    parts = compose(1, [A, B], ["드레싱이 주인공이구려.", "국물까지 원샷했구려."], "말뿐이었소.", [C])
    assert parts == [(f"🐷 **오늘의 식단 평가**\n\n<@{A}> 드레싱이 주인공이구려.\n<@{B}> 국물까지 원샷했구려.\n\n"
                      f"📝 총평: 말뿐이었소.\n🙈 끝내 안 올린 사람: <@{C}>")]
    assert [line for line in unmatched(parts[0]) if not line.startswith("<@")] == []
    many = compose(1, list(range(1, 40)), ["가" * 140] * 39, "끝.", [])
    assert len(many) > 1 and all(len(part) <= 1900 for part in many)
    for text in (NOBODY, FAILED):
        assert unmatched(text) == []


def run_judge(answers, posts, missing=()):
    channel = SimpleNamespace(send=AsyncMock())
    asked = []

    async def ask(prompt, diet):
        asked.append(prompt)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    outcome = asyncio.run(judge_day(1, channel, list(missing), posts, tone=None, ask=ask))
    sent = [call.args[0] for call in channel.send.await_args_list]
    for call in channel.send.await_args_list:
        mentions = call.kwargs["allowed_mentions"]
        assert not mentions.users and not mentions.roles and not mentions.everyone
    return outcome, sent, asked


def test_judge_posts_retries_and_fails_quietly(caplog) -> None:
    caplog.set_level(logging.INFO)
    posts = [post(A, "샐러드", [photo()]), post(B, "라면")]
    outcome, sent, asked = run_judge(["엉망인 답", GOOD], posts, missing=[C])
    assert outcome == "posted" and len(asked) == 2 and asked[1].endswith("다시 쓰시오.")
    assert sent[0].startswith("🐷 **오늘의 식단 평가**") and f"🙈 끝내 안 올린 사람: <@{C}>" in sent[0]
    outcome, sent, _ = run_judge(["엉망", "또 엉망"], posts)
    assert (outcome, sent) == ("failed", [FAILED])
    outcome, sent, _ = run_judge([RuntimeError("model down")], posts)
    assert (outcome, sent) == ("failed", [FAILED])
    assert "샐러드" not in caplog.text and "드레싱" not in caplog.text
    assert "diet_judge people=2 photos=1 calls=2 ok=True" in caplog.text


def test_nobody_posted_needs_no_model() -> None:
    outcome, sent, asked = run_judge([], [], missing=[A, B])
    assert outcome == "nobody" and asked == []
    assert sent == [f"{NOBODY}\n🙈 끝내 안 올린 사람: <@{A}>, <@{B}>"]


def test_the_client_judges_with_its_engine(tmp_path, monkeypatch) -> None:
    from test_p140_tone_notices import toned_client
    calls = []

    class Engine:
        async def diet_review(self, prompt, data, photos):
            calls.append((data, photos))
            return GOOD

    client, tones = toned_client(tmp_path, monkeypatch, None)
    client.summary_workflow.engine = Engine()
    tones.save(1, BY_KEY["mz"].tone, expected_version=0)
    channel = SimpleNamespace(send=AsyncMock())
    home = SimpleNamespace(id=1)

    async def scenario():
        try:
            return await client._diet_judge(home, channel, 70, [C],
                                            [post(A, "샐러드", [photo()]), post(B, "라면")])
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "posted"
    assert calls[0][1] == [(b"\xff\xd8synthetic", ".jpg")]
    assert channel.send.await_args.args[0].startswith("🐷 **오늘의 식단 평가**")

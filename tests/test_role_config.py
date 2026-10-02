"""`/관리권한 설정`: admins and manager roles choose the bot manager roles (T113-P2)."""

import asyncio
import logging
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord import app_commands

from yoyackbot.channel_config import DENIED as CHANNEL_DENIED
from yoyackbot.channel_config import (
    GUILD_ONLY,
    NOT_ALLOWED,
    MemoryWatchStore,
    install_channel_commands,
)
from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.role_config import (
    DENIED,
    INVALID_ROLE,
    AddRoles,
    ClearRoles,
    RemoveRoles,
    RoleSettingsView,
    SaveRoles,
    install_role_commands,
    role_summary,
)

ROLE, OTHER, MANAGED, EVERYONE = 55, 56, 57, 1


def make_role(role_id: int, *, managed: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=role_id, managed=managed, mention=f"<@&{role_id}>",
                           is_default=lambda: role_id == EVERYONE)


ROLES = {r.id: r for r in (make_role(ROLE), make_role(OTHER), make_role(MANAGED, managed=True),
                           make_role(EVERYONE))}


def guild(guild_id: int = 1) -> SimpleNamespace:
    text = Mock(spec=discord.TextChannel)
    text.permissions_for.return_value = SimpleNamespace(
        view_channel=True, read_message_history=True, send_messages=True
    )
    return SimpleNamespace(id=guild_id, me=object(), get_role=ROLES.get,
                           get_channel=lambda cid: text if cid == 10 else None)


def interaction(*, home: object | None, user_id: int = 7, admin: bool = False,
                roles: tuple[int, ...] = ()) -> SimpleNamespace:
    response = SimpleNamespace(done=False, send_message=AsyncMock(), edit_message=AsyncMock())
    response.is_done = lambda: response.done

    async def defer(**kwargs) -> None:
        response.done = True

    response.defer = AsyncMock(side_effect=defer)
    return SimpleNamespace(
        guild=home, guild_id=getattr(home, "id", None),
        user=SimpleNamespace(
            id=user_id, roles=[SimpleNamespace(id=r) for r in roles],
            guild_permissions=SimpleNamespace(administrator=admin, manage_channels=False),
        ),
        response=response,
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
        original_response=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())),
    )


def commands(store: MemoryManagerRoleStore):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    install_channel_commands(tree, MemoryWatchStore(), store)
    install_role_commands(tree, store)
    channel = tree.get_command("채널").get_command("설정")  # type: ignore[union-attr]
    roles = tree.get_command("관리권한").get_command("설정")  # type: ignore[union-attr]
    return channel, roles


def item(view: RoleSettingsView, kind: type):
    return next(child for child in view.children if isinstance(child, kind))


def test_admin_grants_a_role_and_that_role_can_then_use_slash_commands(caplog) -> None:
    caplog.set_level(logging.INFO)
    home = guild()

    async def scenario() -> None:
        store = MemoryManagerRoleStore()
        channel, roles = commands(store)
        member = interaction(home=home, user_id=8, roles=(ROLE,))
        await channel.callback(member)
        assert member.followup.send.await_args.args == (NOT_ALLOWED,)

        admin = interaction(home=home, admin=True)
        await roles.callback(admin)
        view = admin.edit_original_response.await_args.kwargs["view"]
        assert admin.response.defer.await_args.kwargs["ephemeral"] is True
        assert "🛡️ 현재 봇 관리 역할 0개: 없음(관리자만 사용)" in (
            admin.edit_original_response.await_args.kwargs["content"]
        )
        add = item(view, AddRoles)
        add._values = [ROLES[ROLE]]
        await add.callback(interaction(home=home, admin=True))
        await item(view, SaveRoles).callback(interaction(home=home, admin=True))
        assert store.get(1) == frozenset({ROLE})

        member = interaction(home=home, user_id=8, roles=(ROLE,))
        await channel.callback(member)
        assert "view" in member.edit_original_response.await_args.kwargs

        # a manager role member may also manage the roles, and can remove them again
        member = interaction(home=home, user_id=8, roles=(ROLE,))
        await roles.callback(member)
        member_view = member.edit_original_response.await_args.kwargs["view"]
        remove = item(member_view, RemoveRoles)
        remove._values = [ROLES[ROLE]]
        await remove.callback(interaction(home=home, user_id=8, roles=(ROLE,)))
        await item(member_view, SaveRoles).callback(interaction(home=home, user_id=8, roles=(ROLE,)))
        assert store.get(1) == frozenset()
        again = interaction(home=home, user_id=8, roles=(ROLE,))
        await channel.callback(again)
        assert again.followup.send.await_args.args == (NOT_ALLOWED,)

    asyncio.run(scenario())
    saved = [r.getMessage() for r in caplog.records if r.getMessage().startswith("manager_roles_saved")]
    assert len(saved) == 2
    assert all(re.fullmatch(r"manager_roles_saved at=\S+Z count=[01]", line) for line in saved)


@pytest.mark.parametrize("who", [{}, {"roles": (OTHER,)}])
def test_others_and_direct_messages_are_refused(who: dict) -> None:
    async def scenario() -> None:
        _channel, roles = commands(MemoryManagerRoleStore())
        attempt = interaction(home=guild(), **who)
        await roles.callback(attempt)
        assert attempt.followup.send.await_args.args == (NOT_ALLOWED,)
        dm = interaction(home=None, admin=True)
        await roles.callback(dm)
        assert dm.response.send_message.await_args.args == (GUILD_ONLY,)

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [EVERYONE, MANAGED, 999])
def test_everyone_managed_and_unknown_roles_cannot_be_chosen(bad: int) -> None:
    async def scenario() -> None:
        store = MemoryManagerRoleStore()
        view = RoleSettingsView(store, guild_id=1, owner_id=7, snapshot=store.snapshot(1))
        add = item(view, AddRoles)
        add._values = [ROLES.get(bad) or make_role(bad)]
        click = interaction(home=guild(), admin=True)
        await add.callback(click)
        assert click.response.send_message.await_args.args == (INVALID_ROLE,)
        view.draft.add(bad)
        save = interaction(home=guild(), admin=True)
        await item(view, SaveRoles).callback(save)
        if bad == 999:
            assert "사라진 역할" in save.edit_original_response.await_args.kwargs["content"]
        else:
            assert save.followup.send.await_args.args == (INVALID_ROLE,)
        assert store.get(1) == frozenset()

    asyncio.run(scenario())


def test_view_checks_opener_server_role_and_concurrent_edits() -> None:
    async def scenario() -> None:
        store = MemoryManagerRoleStore()
        store.replace(1, frozenset({ROLE}))
        view = RoleSettingsView(store, guild_id=1, owner_id=8, snapshot=store.snapshot(1))
        for home, user_id, who, ok, message in [
            (guild(1), 8, {"roles": (ROLE,)}, True, None),
            (guild(1), 9, {"admin": True}, False, DENIED),
            (guild(2), 8, {"admin": True}, False, DENIED),
            (guild(1), 8, {}, False, NOT_ALLOWED),
        ]:
            click = interaction(home=home, user_id=user_id, **who)
            assert await view.interaction_check(click) is ok
            if message:
                sent = click.followup.send if click.response.is_done() else click.response.send_message
                assert sent.await_args.args[0] == message
        await item(view, ClearRoles).callback(interaction(home=guild(), user_id=8, roles=(ROLE,)))
        store.replace(1, frozenset({ROLE, OTHER}))  # someone else saved meanwhile
        save = interaction(home=guild(), user_id=8, roles=(ROLE,))
        await item(view, SaveRoles).callback(save)
        assert "다른 사람이 설정을 바꾸었소" in save.followup.send.await_args.args[0]
        assert store.get(1) == frozenset({ROLE, OTHER})
        assert view.timeout == 120

    asyncio.run(scenario())


def test_summary_lists_roles() -> None:
    assert role_summary(guild(), {ROLE, OTHER}) == "🛡️ 현재 봇 관리 역할 2개: <@&55>, <@&56>"
    assert role_summary(guild(), {404}) == "🛡️ 현재 봇 관리 역할 1개: 삭제된 역할"


def test_role_view_refusal_points_at_its_own_command() -> None:
    assert "`/관리권한 설정`" in DENIED and "`/채널 설정`" not in DENIED
    assert "`/채널 설정`" in CHANNEL_DENIED and DENIED != CHANNEL_DENIED


def test_open_removes_only_missing_roles_and_keeps_concurrent_valid_addition() -> None:
    class Concurrent(MemoryManagerRoleStore):
        def remove_role(self, guild_id: int, role_id: int) -> bool:
            self.replace(guild_id, self.get(guild_id) | {OTHER})
            return super().remove_role(guild_id, role_id)

    async def scenario() -> None:
        store = Concurrent()
        store.replace(1, frozenset({ROLE, 999}))
        store.replace(2, frozenset({999}))
        request = interaction(home=guild(), admin=True)
        await commands(store)[1].callback(request)
        result = request.edit_original_response.await_args.kwargs
        view = result["view"]
        assert store.get(1) == frozenset({ROLE, OTHER})
        assert store.get(2) == frozenset({999})
        assert view.draft == {ROLE, OTHER}
        assert view.original_version == store.snapshot(1)[0]
        assert "사라진 역할" in result["content"]
        view.draft.remove(ROLE)
        await item(view, SaveRoles).callback(interaction(home=guild(), admin=True))
        assert store.get(1) == frozenset({OTHER})

    asyncio.run(scenario())


def test_cleanup_failure_still_allows_a_fresh_valid_draft_to_save_by_cas() -> None:
    class Broken(MemoryManagerRoleStore):
        def remove_role(self, guild_id: int, role_id: int) -> bool:
            raise RuntimeError("synthetic cleanup failure")

    async def scenario() -> None:
        store = Broken()
        store.replace(1, frozenset({ROLE, 999}))
        request = interaction(home=guild(), admin=True)
        await commands(store)[1].callback(request)
        view = request.edit_original_response.await_args.kwargs["view"]
        assert view.draft == {ROLE}
        assert store.get(1) == frozenset({ROLE, 999})
        view.draft.add(OTHER)
        await item(view, SaveRoles).callback(interaction(home=guild(), admin=True))
        assert store.get(1) == frozenset({ROLE, OTHER})

    asyncio.run(scenario())


@pytest.mark.parametrize("concurrent", [False, True])
def test_save_prunes_vanished_draft_roles_without_overwriting_a_new_revision(concurrent: bool) -> None:
    async def scenario() -> None:
        store = MemoryManagerRoleStore()
        store.replace(1, frozenset({ROLE, 999}))
        view = RoleSettingsView(store, 1, 7, snapshot=store.snapshot(1))
        view.draft.add(OTHER)
        if concurrent:
            store.replace(1, frozenset({ROLE}))
        request = interaction(home=guild(), admin=True)
        await item(view, SaveRoles).callback(request)
        if concurrent:
            assert store.get(1) == frozenset({ROLE})
            assert "다른 사람이 설정을 바꾸었소" in request.followup.send.await_args.args[0]
            request.edit_original_response.assert_not_awaited()
        else:
            assert store.get(1) == frozenset({ROLE, OTHER})
            assert "사라진 역할" in request.edit_original_response.await_args.kwargs["content"]

    asyncio.run(scenario())


def test_expired_or_revoked_role_view_cannot_save() -> None:
    async def scenario() -> None:
        store = MemoryManagerRoleStore()
        store.replace(1, frozenset({ROLE}))
        expired = RoleSettingsView(store, 1, 7, snapshot=store.snapshot(1))
        expired.draft.clear()
        await expired.on_timeout()
        request = interaction(home=guild(), admin=True)
        await item(expired, SaveRoles).callback(request)
        assert "설정 시간이 지났소" in request.response.send_message.await_args.args[0]
        assert store.get(1) == frozenset({ROLE})
        revoked = RoleSettingsView(store, 1, 7, snapshot=store.snapshot(1))
        revoked.draft.add(OTHER)
        store.replace(1, frozenset())
        request = interaction(home=guild(), roles=(ROLE,))
        await item(revoked, SaveRoles).callback(request)
        assert request.followup.send.await_args.args == (NOT_ALLOWED,)
        assert store.get(1) == frozenset()

    asyncio.run(scenario())

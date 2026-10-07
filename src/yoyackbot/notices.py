"""1.4.0 server-tone notices: the bot's fixed notices, and each server's rewritten copy.

Every notice the bot sends is a catalog entry: a key and the default text, where `{name}` marks
a value filled in at send time. A server with its own tone gets a rewritten copy of the catalog
(see `notice_writer`); `localize` maps an outgoing default text to that server's copy, line by
line, keeping the filled-in values. `!!말하자면`/`/말하자면` notices are not in the catalog (user
decision), and model output (summaries, ratings) never passes through here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from threading import RLock

from yoyackbot.output_quality import HATE_TERMS
from yoyackbot.parser import HELP_TEMPLATE

MESSAGE_LIMIT = 2000  # Discord's limit; a rewritten message that would not fit stays default
HELP_LIMIT = 2000
_FIELD = re.compile(r"\{([a-z_]+)\}")
_COMMAND = re.compile(r"`[^`\n]+`|[!/][!가-힣A-Za-z]+")
_DIGITS = re.compile(r"[0-9]+(?:[,.][0-9]+)*")
_MENTION_LIKE = re.compile(r"<[@#&!:a-z]|@everyone|@here|https?://|discord\.gg", re.IGNORECASE)
_EMOJI_LEAD = re.compile(r"^[^\w\s`*(<{\[\"'‘“«#>-]+")
# Filled with a finished short sentence ("3곳이오.") or someone's own words, so nothing may follow.
SENTENCE_FIELDS = ("value", "stage", "reason")


@dataclass(frozen=True)
class Notice:
    key: str
    text: str
    part: bool = False  # only ever a value inside another notice (e.g. "3분 전이오.")
    pattern: re.Pattern[str] = field(init=False, repr=False, compare=False)
    fields: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        names = tuple(_FIELD.findall(self.text))
        object.__setattr__(self, "fields", names)
        object.__setattr__(self, "pattern", _compile(self.text))

    @property
    def literal(self) -> str:
        return _FIELD.sub("", self.text)

    @property
    def limit(self) -> int:
        if self.key == "help":
            return HELP_LIMIT
        return max(3 * len(self.text), 60)


def _compile(template: str) -> re.Pattern[str]:
    out, seen, last = [], set(), 0
    for match in _FIELD.finditer(template):
        out.append(re.escape(template[last:match.start()]))
        name = match.group(1)
        out.append(f"(?P={name})" if name in seen else f"(?P<{name}>[^\n]*?)")
        seen.add(name)
        last = match.end()
    out.append(re.escape(template[last:]))
    return re.compile("".join(out))


def fill(template: str, values: Mapping[str, str]) -> str:
    return _FIELD.sub(lambda match: values.get(match.group(1), match.group(0)), template)


_ENTRIES = (
    # 도움말 (1.3.1 `/도움말`); `{two_days}` is " `2일`" or empty, `{max_days}` the day limit.
    Notice("help", HELP_TEMPLATE),
    Notice("help.moved", "📜 사용법은 `/도움말`로 보시오. 부른 사람에게만 보이오. 🙈"),
    Notice("command.unclear", "🤔 그 명은 알아듣기 어렵소. `/도움말`에서 사용법을 살펴보시오. 📜"),
    Notice("command.limit", "📏 {unit} 단위는 1부터 {maximum}까지 고르시오. `/도움말`에서 사용법을 살펴보시오. 📜"),
    Notice("command.preview", "🚧 요약 요청을 해석했소. 실제 요약 기능은 아직 준비 중이오. 🛠️"),
    # 요약 시작·대기·실패·쿨타임
    Notice("summary.start", "📝 {scope} 채팅을 {mode}요약해보겠소. ✍️"),
    Notice("summary.reply_ignored", "↩️ 답장한 메시지 기준으로 요약하오(기간·개수는 무시했소)."),
    Notice("summary.busy_scope", "⏳ 현재 {subject} 채팅을 {mode}요약중이오. 🔄"),
    Notice("summary.busy_patience", "🧘 참을성을 가져보시오. 🙏"),
    Notice("summary.busy", "⏳ 요약중이오. 좀 기다리시오. 🙏"),
    Notice("summary.cooldown", "🧊 아직은 때가 아니오. {minutes}분 {seconds}초 뒤에 오시오. ⏰"),
    Notice("summary.cooldown_plain", "🧊 아직은 때가 아니오. 잠시 뒤에 오시오. ⏰"),
    Notice("summary.empty", "🍃 해당 범위에 요약할 일반 사용자 대화가 없소. 🤷"),
    Notice("summary.history_failed", "📂 대화를 불러오지 못하였소. 잠시 뒤 다시 시도하시오. 🔁"),
    Notice("summary.model_failed", "😵 요약에 실패하였소. 잠시 뒤 다시 명하시오. 🔁"),
    Notice("summary.send_failed", "📮 요약을 전하지 못하였소. 잠시 뒤 다시 시도하시오. 🔁"),
    Notice("summary.failed", "⚠️ 요약을 마치지 못했소. 잠시 후 다시 시도하시오. 😵"),
    Notice("summary.invalidated", "🛑 채널 주시나 권한이 바뀌어 요약을 멈추었소. 🔒"),
    Notice("summary.queue_full", "🚦 요약 요청이 몰렸소. 잠시 후 다시 시도하시오. 🙏"),
    Notice("summary.queue_timeout", "⌛ 요약 대기 시간이 지났소. 다시 시도하시오. 🔁"),
    Notice("summary.closing", "🔌 봇이 종료 중이오. 잠시 후 다시 시도하시오. 💤"),
    Notice("summary.too_large", "📚 요약할 대화가 너무 많소. 기간이나 메시지 개수를 줄여 다시 명하시오. ✂️"),
    Notice("summary.note_too_long", "✂️ 추가 요청은 200자까지만 알아듣겠소. 📏"),
    Notice("summary.header", "🗓️ {label}부터 지금까지의 요약이오."),
    Notice("summary.header_clock", "🗓️ {label}부터 지금까지의 요약이오. (⏰ 기준: {clock} KST)"),
    Notice("summary.usage_exhausted", "🪫 요약봇 사용량이 정상화되었소. 😵"),
    Notice("summary.usage_blessing", "🙏 초기화의 가호가 함께하길... ✨"),
    Notice("reply.other_channel", "↩️ 같은 채널의 메시지에 답장해야 그 메시지부터 요약하오. 🙅"),
    Notice("reply.missing", "🔍 답장한 메시지를 찾을 수 없소. 지워졌는지 확인하시오. 🗑️"),
    Notice("reply.lookup_failed", "⚠️ 답장한 메시지를 확인하지 못했소. 잠시 후 다시 시도하시오. 🔁"),
    Notice("reply.too_old", "📅 답장한 메시지가 너무 오래됐소. 최근 {days}일 안의 메시지에 답장하시오. ⏳"),
    Notice("reply.too_many", "📚 답장한 메시지부터 대화가 {count}개를 넘소. 더 가까운 메시지에 답장하시오. ✂️"),
    # 채널 주시·수집
    Notice("watch.unwatched", "👀 이 채널은 아직 살피고 있지 않소. `/채널 설정`으로 먼저 정하시오. 🛠️"),
    Notice("watch.unavailable", "⚠️ 채널 설정을 확인하지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("collect.start", "👋📥 안녕하시오. 요약을 위해 데이터 수집중이오. ⏳"),
    Notice("collect.ready", "✅🎉 이제부터 요약을 해줄 수 있을 것 같소. 📝"),
    Notice("collect.not_ready", "⏳ 참을성을 기르시오 아직 준비가 되지 않았소. 🧘"),
    Notice("collect.initial", "📥 처음 수집하는 중이오."),
    Notice("collect.recheck", "🔄 연결이 끊긴 사이의 대화와 수정·삭제를 대조하는 중이오."),
    Notice("collect.retry", "⏳ 잠시 막혀 다시 시도하려고 기다리는 중이오."),
    Notice("collect.blocked", "🚫 수집이 막혔소."),
    Notice("collect.notice", "📣 수집은 끝났고 준비 안내를 올리려는 중이오."),
    Notice("collect.gap", "🔌 연결이 끊겼던 구간을 점검하려고 기다리는 중이오."),
    Notice("collect.ok", "✅ 요약할 수 있소."),
    Notice("collect.unknown", "❔ 수집 형편을 확인할 수 없소."),
    Notice("collect.no_permission", "🔒 이유: 이 채널을 읽거나 쓸 권한이 없소."),
    Notice("collect.channel_gone", "🗑️ 이유: 채널을 찾을 수 없소."),
    Notice("collect.invalid_page", "🧩 이유: Discord 응답이 이상해 멈췄소."),
    Notice("collect.reason_unknown", "❔ 이유: 확인할 수 없소."),
    Notice("collect.worker_stopped", "⚠️ 수집 일꾼이 지금 멈춰 있소. 관리자에게 알리시오."),
    Notice("collect.stage", "📍 이 채널 수집: {stage}"),
    Notice("collect.stored_label", "💬 저장된 대화: {value}"),
    Notice("collect.pages", "📄 이번 수집에서 처리한 쪽: {value}"),
    Notice("collect.progress", "🕒 마지막 진척: {value}"),
    Notice("collect.stored", "💬 이 채널에 저장된 대화: {count}건이오."),
    Notice("collect.next_retry", "🔁 다음 재시도: {value}"),
    Notice("collect.brief", "📄 처리 {pages} · 💬 저장 {count}건"),
    # 상태·사용량·채널 목록
    Notice("status.title", "📜🔍 현재 형편을 살펴보았소. 🧐"),
    Notice("status.calm", "🩺 상태: 평온하오. 😌"),
    Notice("status.check", "🩺 상태: 점검이 필요하오. 🚨"),
    Notice("status.channels", "📡 주시 채널: {value}"),
    Notice("status.cached", "💬 캐시된 대화: {value}"),
    Notice("status.database", "💾 DB 크기: {value}"),
    Notice("status.model", "🤖 Codex: {model}"),
    Notice("status.last", "🕒 마지막 요약: {value}"),
    Notice("usage.unavailable", "🌫️ Codex 사용량을 지금 확인할 수 없소. 잠시 후 다시 시도하시오. 🙏"),
    Notice("usage.title", "🔮✨ Codex의 기운을 살펴보았소. 👀"),
    Notice("usage.five_hour", "⏱️ 5시간 한도는 {percent}% 남았소. 🔋"),
    Notice("usage.weekly", "📅 주간 한도는 {percent}% 남았소. 🗓️"),
    Notice("usage.warning", "🟠⚠️ 요약 정상화가 버겁기 시작했소. 😰"),
    Notice("usage.ok", "🟢💪 아직 요약을 정상화하기엔 넉넉하오. 😎"),
    Notice("channels.header", "📡👀 지금 본인이 보고 있는 채널을 알려주겠소"),
    Notice("channels.footer", "✅ 이상이오. 🫡"),
    Notice("channels.empty", "🫥 지금 보고 있는 채널이 없소. `/채널 설정`으로 정하시오. 🛠️"),
    Notice("channels.sent", "📨 목록을 개인 메시지로 전달했소."),
    Notice("channels.dm_failed", "📭 목록을 개인 메시지로 전달하지 못했소. DM 수신 설정을 확인하시오."),
    # values inside the lines above
    Notice("value.unknown", "확인할 수 없소.", part=True),
    Notice("value.none_yet", "아직 없소.", part=True),
    Notice("value.no_record", "기록이 없소.", part=True),
    Notice("value.pages", "{count}쪽이오.", part=True),
    Notice("value.places", "{count}곳이오.", part=True),
    Notice("value.items", "{count}건이오.", part=True),
    Notice("value.megabytes", "{size} MB이오.", part=True),
    Notice("value.just_now", "방금 전이오.", part=True),
    Notice("value.minutes_ago", "{count}분 전이오.", part=True),
    Notice("value.hours_ago", "{count}시간 전이오.", part=True),
    Notice("value.days_ago", "{count}일 전이오.", part=True),
    Notice("value.soon", "곧이오.", part=True),
    Notice("value.minutes_later", "{count}분 뒤이오.", part=True),
    Notice("value.hours_later", "{count}시간 뒤이오.", part=True),
    Notice("value.admins_only", "없음(관리자만 사용)", part=True),
    Notice("value.no_reason", "사유 없음", part=True),
    Notice("value.unknown_person", "알 수 없는 사람", part=True),
    # 설정 화면 (/채널 설정, /관리권한 설정, /말투, /속도 설정, /처형설정)
    Notice("settings.guild_only", "🏠 서버 안에서만 쓸 수 있소. 🙅"),
    Notice("settings.not_allowed", "🔒 이 명령은 관리자나 봇 관리 역할만 쓸 수 있소. 🛡️"),
    Notice("settings.denied", "🚫 이 설정 화면은 연 사람만 쓸 수 있소. 명령을 직접 여시오. 🙅"),
    Notice("settings.expired", "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁"),
    Notice("settings.changed", "🔄 다른 사람이 설정을 바꾸었소. 명령을 다시 열어 확인하시오. 👀"),
    Notice("settings.save_failed", "⚠️ 설정을 저장하지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("settings.read_failed", "⚠️ 설정을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("settings.cancelled", "↩️ 설정 변경을 취소했소. 🙆"),
    Notice("settings.closed", "👋 설정 화면을 닫았소."),
    Notice("settings.press_save", "💾 저장을 눌러 확정하시오. 👇"),
    Notice("settings.saved", "💾✅ 저장했소."),
    Notice("settings.edit_hint", "🛠️ 추가·제거 후 저장하거나 전체 해제를 고르시오. 👇"),
    Notice("settings.admins_always", "👑 관리자는 언제나 쓸 수 있소."),
    Notice("settings.invalid_role", "⚠️ 고를 수 없는 역할이 있소. @everyone과 봇·연동이 관리하는 역할은 고를 수 없소. 🙅"),
    Notice("watch_settings.denied", "🚫 이 설정 화면은 연 사람만 쓸 수 있소. `/채널 설정`을 직접 여시오. 🙅"),
    Notice("watch_settings.invalid", "⚠️ 봇이 접근할 수 있는 서버의 텍스트 채널만 고르시오. 📡"),
    Notice("watch_settings.current", "📡 현재 주시 채널 {count}개: {channels}"),
    Notice("watch_settings.cleared", "🧹 목록을 비웠소. 저장을 눌러 확정하시오. 👇"),
    Notice("watch_settings.saved", "💾✅ 주시 채널 {count}개를 저장했소. 🎉"),
    Notice("role_settings.denied", "🚫 이 설정 화면은 연 사람만 쓸 수 있소. `/관리권한 설정`을 직접 여시오. 🙅"),
    Notice("role_settings.dropped", "🧹 서버에서 사라진 역할을 선택 목록에서 제외했소."),
    Notice("role_settings.current", "🛡️ 현재 봇 관리 역할 {count}개: {roles}"),
    Notice("role_settings.cleared", "🧹 목록을 비웠소(관리자만 쓰게 됨). 저장을 눌러 확정하시오. 👇"),
    Notice("role_settings.saved", "💾✅ 봇 관리 역할 {count}개를 저장했소. 🎉"),
    Notice("tone.denied", "🚫 이 말투 화면은 연 사람만 쓸 수 있소. `/말투`를 직접 여시오. 🙅"),
    Notice("tone.expired", "⌛ 말투 화면 시간이 지났소. `/말투`를 다시 여시오. 🔁"),
    Notice("tone.changed", "🔄 다른 사람이 말투를 바꾸었소. `/말투`를 다시 열어 확인하시오. 👀"),
    Notice("tone.length", "✂️ 말투는 1자 이상 1,500자 이하로 쓰시오. 📏"),
    Notice("tone.save_failed", "⚠️ 말투를 저장하지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("tone.read_failed", "⚠️ 말투를 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("tone.saved", "💾✅ 말투를 저장했소. 🎭"),
    Notice("tone.reset", "↩️ 기본 말투로 돌아갔소. 🙆"),
    Notice("tone.closed", "👋 말투 화면을 닫았소."),
    Notice("tone.current_default", "🎭 지금 적용 중인 말투: 기본 말투"),
    Notice("tone.current_server", "🎭 지금 적용 중인 말투: 이 서버 말투"),
    Notice("tone.edit_hint", "✏️ 수정하거나 기본값으로 되돌릴 수 있소. 👇"),
    Notice("tone.notices_writing", "📝 이 서버의 안내 문구를 새 말투로 고쳐 쓰는 중이오. 끝나면 알려주겠소. ⏳"),
    Notice("tone.notices_done", "🎭✅ 안내 문구 {written}개를 이 서버 말투로 바꾸었소. 🎉"),
    Notice("tone.notices_partial", "🎭 안내 문구 {written}개를 바꾸었고, 바꾸지 못한 {kept}개는 기본 문구를 쓰오. 🔧"),
    Notice("tone.notices_failed", "⚠️ 안내 문구를 새 말투로 바꾸지 못해 기본 문구를 쓰오. 말투를 다시 저장하면 다시 해보겠소. 🔧"),
    Notice("speed.denied", "🚫 이 속도 화면은 연 사람만 쓸 수 있소. `/속도 설정`을 직접 여시오. 🙅"),
    Notice("speed.expired", "⌛ 속도 화면 시간이 지났소. `/속도 설정`을 다시 여시오. 🔁"),
    Notice("speed.save_failed", "⚠️ 속도 설정을 저장하지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("speed.read_failed", "⚠️ 속도 설정을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("speed.turned_on", "⚡✅ 빠른 모드를 켰소."),
    Notice("speed.turned_off", "🐢✅ 빠른 모드를 껐소."),
    Notice("speed.closed", "👋 속도 화면을 닫았소."),
    Notice("speed.explain", "💡 켜면 이 서버의 요약·`!!말하자면`이 더 빨리 나오지만 Codex 사용량이 더 들 수 있소."),
    Notice("speed.state_on", "⚡ 빠른 모드: 켜짐"),
    Notice("speed.state_off", "🐢 빠른 모드: 꺼짐(기본)"),
    Notice("speed.choose", "🛠️ 켜기·끄기를 고르시오. 👇"),
    Notice("execution_settings.admin_only", "🚫 처형 역할은 서버 관리자만 정할 수 있소. 🙅"),
    Notice("execution_settings.invalid_channel", "⚠️ 봇이 그 채널을 보고 글을 쓸 수 있어야 하오. 다른 텍스트 채널을 고르시오. 🙅"),
    Notice("execution_settings.no_audit", "⚠️ 봇에 감사 로그 보기 권한이 없어 지금은 처형 로그를 올릴 수 없소. 🔧"),
    Notice("execution_settings.no_channel", "📜 처형 로그 채널: 없음(로그를 올리지 않음)"),
    Notice("execution_settings.channel", "📜 처형 로그 채널: {channel}"),
    Notice("execution_settings.roles", "⚔️ 처형 역할 {count}개: {roles}"),
    Notice("execution_settings.channel_cleared", "🧹 처형 로그를 올리지 않게 했소. 저장을 눌러 확정하시오. 👇"),
    Notice("execution_settings.roles_cleared", "🧹 처형 역할을 비웠소(관리자만 사용). 저장을 눌러 확정하시오. 👇"),
    Notice("execution_settings.channel_hint", "🛠️ 채널을 고르고 저장하거나 해제하시오. 👇"),
    Notice("execution_settings.roles_hint", "🛠️ 역할을 고르고 저장하시오. 👑 관리자는 언제나 쓸 수 있소. 👇"),
    # 처형 로그와 /처형
    Notice("execution_log.apply", "⚔️ **처형** — 처형자 {executor} → 처형인 {target}"),
    Notice("execution_log.extend", "⚔️ **처형 연장** — 처형자 {executor} → 처형인 {target}"),
    Notice("execution_log.until", "⏱️ {duration} ({until}까지)"),
    Notice("execution_log.reason", "📝 사유: {reason}"),
    Notice("execution_log.release", "🕊️ **사면** — {executor}이(가) {target}의 처형을 풀었소."),
    Notice("execute.done", "⚔️ {target}을(를) {duration} 동안 처형했소. 📝 사유: {reason}"),
    Notice("execute.not_allowed", "🚫 처형은 처형 역할이 있는 사람이나 관리자만 할 수 있소. 🙅"),
    Notice("execute.bad_time", "⏱️ 시간은 `30초`·`10분`·`2시간`·`1일`처럼 쓰시오(숫자만 쓰면 초, 최대 28일). 📏"),
    Notice("execute.long_reason", "✂️ 사유는 400자까지만 쓰시오. 📏"),
    Notice("execute.self", "🙃 자기 자신은 처형할 수 없소."),
    Notice("execute.bot", "🤖 봇은 처형할 수 없소."),
    Notice("execute.protected", "🛡️ 서버 주인이나 관리자는 처형할 수 없소."),
    Notice("execute.higher", "⬆️ 자기와 같거나 높은 역할의 사람은 처형할 수 없소."),
    Notice("execute.bot_cannot", "🔧 봇에 타임아웃 권한이 없거나 봇의 역할이 그 사람보다 낮아 처형할 수 없소."),
    Notice("execute.failed", "⚠️ 처형하지 못했소. 잠시 후 다시 시도하시오. 🔧"),
    Notice("execute.read_failed", "⚠️ 처형 설정을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"),
)
CATALOG: dict[str, Notice] = {entry.key: entry for entry in _ENTRIES}
_EXACT = {entry.text: entry for entry in _ENTRIES if not entry.fields}
# Longest fixed text first, so "📜 처형 로그 채널: {channel}" never shadows a longer match.
_TEMPLATES = sorted(
    (entry for entry in _ENTRIES if entry.fields), key=lambda entry: -len(entry.literal),
)


def _match(text: str, *, parts: bool) -> tuple[Notice, dict[str, str]] | None:
    entry = _EXACT.get(text)
    if entry is not None and (parts or not entry.part):
        return entry, {}
    for entry in _TEMPLATES:
        if entry.part and not parts:
            continue
        found = entry.pattern.fullmatch(text)
        if found is not None:
            return entry, found.groupdict()
    return None


def _render(text: str, table: Mapping[str, str], *, value: bool = False) -> str | None:
    """`text` in the server's words, or None when it is not a catalog notice."""
    found = _match(text, parts=value)
    if found is None:
        return None
    entry, values = found
    if not value:  # one level: values inside a notice may be notices themselves
        values = {name: _render(item, table, value=True) or item for name, item in values.items()}
    return fill(table.get(entry.key, entry.text), values)


def render(text: str, table: Mapping[str, str]) -> str:
    """A whole message for one server: the help as a whole, anything else line by line."""
    if not table:
        return text
    whole = _render(text, table)
    if whole is None:
        whole = "\n".join(_render(line, table) or line for line in text.split("\n"))
    return whole if len(whole) <= MESSAGE_LIMIT else text


def unmatched(text: str) -> list[str]:
    """Lines of an outgoing notice that are not in the catalog (for the coverage test)."""
    if _match(text, parts=False) is not None:
        return []
    return [line for line in text.split("\n") if line.strip() and _match(line, parts=False) is None]


class NoticeBook:
    """Each server's validated notices in memory, so a send never waits on the database."""

    def __init__(self) -> None:
        self._tables: dict[int, dict[str, str]] = {}
        self._lock = RLock()

    def load(self, tables: Mapping[int, Mapping[str, str]]) -> None:
        with self._lock:
            self._tables = {guild: dict(table) for guild, table in tables.items() if table}

    def set(self, guild_id: int, table: Mapping[str, str]) -> None:
        with self._lock:
            if table:
                self._tables[guild_id] = dict(table)
            else:
                self._tables.pop(guild_id, None)

    def clear(self, guild_id: int) -> None:
        with self._lock:
            self._tables.pop(guild_id, None)

    def table(self, guild_id: int | None) -> dict[str, str]:
        with self._lock:
            return self._tables.get(guild_id, {}) if guild_id is not None else {}

    def has(self, guild_id: int) -> bool:
        with self._lock:
            return guild_id in self._tables


BOOK = NoticeBook()


def localize(guild_id: int | None, text: str) -> str:
    """The server's own wording of an outgoing notice; unknown text passes unchanged."""
    return render(text, BOOK.table(guild_id))


# --- validation of a rewritten entry ------------------------------------------------------

def _commands(text: str) -> list[str]:
    return sorted(_COMMAND.findall(_FIELD.sub(" ", text)))


def _lead_emoji(text: str) -> str:
    found = _EMOJI_LEAD.match(text)
    return found.group(0).strip() if found else ""


def problem(entry: Notice, text: str) -> str | None:
    """Why a rewritten entry may not replace the default, or None. Only category names leave."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if len(text) > entry.limit:
        return "length"
    if len(_MENTION_LIKE.findall(text)) > len(_MENTION_LIKE.findall(entry.text)):
        return "mention"
    if sorted(_FIELD.findall(text)) != sorted(entry.fields):
        return "placeholder"
    if "{" in _FIELD.sub("", text) or "}" in _FIELD.sub("", text):
        return "brace"
    if any(entry.text.endswith(f"{{{name}}}") and not text.rstrip().endswith(f"{{{name}}}")
           for name in SENTENCE_FIELDS):
        return "placeholder"
    if _commands(text) != _commands(entry.text):
        return "command"
    if sorted(_DIGITS.findall(_FIELD.sub(" ", text))) != sorted(_DIGITS.findall(entry.literal)):
        return "number"
    if text.count("\n") != entry.text.count("\n") and entry.key != "help":
        return "lines"
    if any(term in text for term in HATE_TERMS):
        return "hate"
    lead = _lead_emoji(entry.text)
    if lead and not text.startswith(lead):
        return "emoji"
    return None


def keep_valid(rewritten: Mapping[str, object]) -> tuple[dict[str, str], dict[str, int]]:
    """Valid rewrites by key, and the count of each rejection reason."""
    valid: dict[str, str] = {}
    reasons: dict[str, int] = {}
    for key, text in rewritten.items():
        entry = CATALOG.get(key)
        if entry is None:
            continue
        reason = problem(entry, text) if isinstance(text, str) else "empty"
        if reason is None:
            valid[key] = _keep_line_ends(entry.text, text.strip("\n"))
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
    return valid, reasons


def _keep_line_ends(default: str, text: str) -> str:
    """The help's two-space Discord line breaks survive a rewrite that trimmed them."""
    if "\n" not in default:
        return text.rstrip() + ("  " if default.endswith("  ") else "")
    return text


def entries(keys: Iterable[str] | None = None) -> list[Notice]:
    return [CATALOG[key] for key in keys] if keys is not None else list(_ENTRIES)

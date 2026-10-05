"""Show `request_timing` lines (1.3.2) from the service journal as per-stage ms tables.

    journalctl --namespace yoyackbot-dev -u yoyackbot-dev -o cat | python scripts/show_timings.py [N]

Only stage names and numbers are read; the lines carry no message or model text.
"""

import json
import sys

STAGE_NAMES = {
    "received": "명령 수신", "admitted": "접수(슬롯·쿨타임 통과)", "start_notice": "시작 안내 전송",
    "collected": "메시지 조회 완료", "queued": "모델 대기열 확보", "posted": "게시 완료",
}
RETRIES = {"summary_retry", "candidates_retry", "idiom_candidates_retry"}


def timings(lines):
    for line in lines:
        start = line.find('{"')
        if start < 0 or "request_timing" not in line:
            continue
        try:
            item = json.loads(line[start:])
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("event") == "request_timing":
            yield item


def ms(value) -> str:
    return "—" if value is None else f"{value:,}"


def render(item: dict) -> str:
    rows = [(f"■ {item['kind']} {item['request_id']} · {item['outcome']} · "
             f"Discord 지연 {ms(item.get('discord_delay_ms'))}ms · 총 {ms(item['total_ms'])}ms")]
    events = [(at, f"{STAGE_NAMES.get(name, name)}", "") for name, at in item["steps"]]
    for call in item["codex"]:
        tag = f"Codex #{call['n']} {call['call']}" + (" (재시도)" if call["call"] in RETRIES else "")
        took = (call["end"] - call["start"]) if call["end"] is not None else None
        first = (call["first_output"] - call["start"]) if call["first_output"] is not None else None
        events.append((call["start"], f"{tag} 시작", ""))
        if call["first_output"] is not None:
            events.append((call["first_output"], f"{tag} 첫 출력", f"시작 +{ms(first)}"))
        if call["end"] is not None:
            extra = "".join((
                f" · {call['effort']}" if call.get("effort") else "",
                f" · 도구 {call['execs']}회" if call.get("execs") is not None else "",
                f" · {ms(call['tokens'])}토큰" if call.get("tokens") is not None else "",
            ))  # 1.3.3 fields; older lines simply lack them
            events.append((call["end"], f"{tag} 완료({call['result']})", f"호출 {ms(took)}{extra}"))
    events.sort(key=lambda event: event[0])
    previous = 0
    for at, name, note in events:
        rows.append(f"  {ms(at):>8}ms  (+{ms(at - previous):>7})  {name}" + (f"  [{note}]" if note else ""))
        previous = at
    rows.append(f"  {ms(item['total_ms']):>8}ms  (+{ms(item['total_ms'] - previous):>7})  작업 종료")
    return "\n".join(rows)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    found = list(timings(sys.stdin))[-limit:]
    print("\n\n".join(render(item) for item in found) if found else "request_timing 줄이 없소.")


if __name__ == "__main__":
    main()

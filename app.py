from __future__ import annotations

import csv
import hashlib
from html import escape as html_escape
import json
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st


APP_TITLE = "합주기가 됩시다 합"
DATA_DIR = Path(__file__).parent / "data"
ROOMS_FILE = DATA_DIR / "rooms.csv"
MEMBERS_FILE = DATA_DIR / "members.csv"
AVAILABILITY_FILE = DATA_DIR / "availability.csv"

ROOM_FIELDS = [
    "room_code",
    "room_name",
    "host_name",
    "password_hash",
    "start_date",
    "end_date",
    "unavailable_windows",
    "created_at",
]
MEMBER_FIELDS = ["room_code", "name", "role", "joined_at"]
AVAILABILITY_FIELDS = ["room_code", "member_name", "date", "time", "status"]

STATUS_OPTIONS = [
    "합주 완전 가능",
    "합주 가능(애매)",
    "합주 가능(불편)",
    "합주 완전 불가",
]

STATUS_COLORS = {
    STATUS_OPTIONS[0]: "#16a34a",
    STATUS_OPTIONS[1]: "#facc15",
    STATUS_OPTIONS[2]: "#f97316",
    STATUS_OPTIONS[3]: "#ef4444",
}
STATUS_CLASSES = {
    STATUS_OPTIONS[0]: "fully-available",
    STATUS_OPTIONS[1]: "maybe-available",
    STATUS_OPTIONS[2]: "uncomfortable",
    STATUS_OPTIONS[3]: "unavailable",
}
STATUS_MARKERS = {
    STATUS_OPTIONS[0]: "🟩",
    STATUS_OPTIONS[1]: "🟨",
    STATUS_OPTIONS[2]: "🟧",
    STATUS_OPTIONS[3]: "🟥",
}
CLEAR_STATUS = "입력 지우기"
LEGACY_STATUS_MAP = {
    "합주 가능": STATUS_OPTIONS[0],
    "노력하면 가능": STATUS_OPTIONS[1],
    "최대한 안 하면 좋겠지만 잘 하면 가능": STATUS_OPTIONS[2],
}


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path, fields in (
        (ROOMS_FILE, ROOM_FIELDS),
        (MEMBERS_FILE, MEMBER_FIELDS),
        (AVAILABILITY_FILE, AVAILABILITY_FIELDS),
    ):
        if not path.exists():
            with path.open("w", encoding="utf-8-sig", newline="") as file:
                csv.DictWriter(file, fieldnames=fields).writeheader()


def read_rows(path: Path) -> list[dict[str, str]]:
    ensure_data_files()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    except (OSError, csv.Error) as error:
        st.error(f"{path.name} 파일을 읽지 못했습니다: {error}")
        return []


def write_rows(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temporary_path.replace(path)
    except OSError as error:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(f"{path.name} 파일을 저장하지 못했습니다: {error}") from error


def save_room(room: dict[str, Any]) -> None:
    rooms = read_rows(ROOMS_FILE)
    for index, saved_room in enumerate(rooms):
        if saved_room["room_code"] == room["room_code"]:
            rooms[index] = room
            break
    else:
        rooms.append(room)
    write_rows(ROOMS_FILE, ROOM_FIELDS, rooms)


def save_member(room_code: str, name: str, role: str = "멤버") -> None:
    members = read_rows(MEMBERS_FILE)
    for member in members:
        if member["room_code"] == room_code and member["name"] == name:
            return
    members.append(
        {
            "room_code": room_code,
            "name": name,
            "role": role,
            "joined_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    write_rows(MEMBERS_FILE, MEMBER_FIELDS, members)


def save_availability(
    room_code: str, member_name: str, selected_date: date, start_minute: int, end_minute: int, status: str
) -> None:
    entries = read_rows(AVAILABILITY_FILE)
    day_string = selected_date.isoformat()
    for minute in range(start_minute, end_minute, 15):
        slot_time = minute_to_time(minute)
        updated = False
        for entry in entries:
            if (
                entry["room_code"] == room_code
                and entry["member_name"] == member_name
                and entry["date"] == day_string
                and entry["time"] == slot_time
            ):
                entry["status"] = status
                updated = True
                break
        if not updated:
            entries.append(
                {
                    "room_code": room_code,
                    "member_name": member_name,
                    "date": day_string,
                    "time": slot_time,
                    "status": status,
                }
            )
    write_rows(AVAILABILITY_FILE, AVAILABILITY_FIELDS, entries)


def clear_availability_slot(
    room_code: str, member_name: str, selected_date: date, minute: int
) -> None:
    day_string = selected_date.isoformat()
    slot_time = minute_to_time(minute)
    entries = read_rows(AVAILABILITY_FILE)
    remaining = [
        entry
        for entry in entries
        if not (
            entry["room_code"] == room_code
            and entry["member_name"] == member_name
            and entry["date"] == day_string
            and entry["time"] == slot_time
        )
    ]
    if len(remaining) != len(entries):
        write_rows(AVAILABILITY_FILE, AVAILABILITY_FIELDS, remaining)


def migrate_legacy_statuses() -> None:
    entries = read_rows(AVAILABILITY_FILE)
    changed = False
    for entry in entries:
        replacement = LEGACY_STATUS_MAP.get(entry.get("status", ""))
        if replacement:
            entry["status"] = replacement
            changed = True
    if changed:
        write_rows(AVAILABILITY_FILE, AVAILABILITY_FIELDS, entries)


def make_room_code(existing_codes: set[str]) -> str:
    for _ in range(100):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in existing_codes:
            return code
    raise RuntimeError("사용할 수 있는 방 코드를 만들지 못했습니다. 다시 시도해 주세요.")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def room_password_enabled(room: dict[str, str]) -> bool:
    return bool(room.get("password_hash", "").strip())


def verify_room_password(room: dict[str, str], password: str) -> bool:
    saved = room.get("password_hash", "").strip()
    if not saved:
        return True
    return secrets.compare_digest(saved, hash_password(password))


def set_room_session(room_code: str, member_name: str) -> None:
    st.session_state["room_code"] = room_code
    st.session_state["member_name"] = member_name
    st.query_params["room"] = room_code
    st.query_params["member"] = member_name


def clear_room_session() -> None:
    st.session_state.pop("room_code", None)
    st.session_state.pop("member_name", None)
    for key in ("room", "member"):
        st.query_params.pop(key, None)


def restore_room_from_query() -> None:
    if st.session_state.get("room_code") and st.session_state.get("member_name"):
        return
    room_code = st.query_params.get("room", "").strip()
    member_name = st.query_params.get("member", "").strip()
    if not room_code or not member_name:
        return
    room = get_room(room_code)
    if not room:
        return
    if not any(member["name"] == member_name for member in room_members(room_code)):
        return
    if room_password_enabled(room):
        return
    set_room_session(room_code, member_name)


def apply_paint_ranges_from_query() -> None:
    payload = st.query_params.get("paint", "").strip()
    if not payload:
        return
    room_code = st.query_params.get("room", "").strip()
    member_name = st.query_params.get("member", "").strip()
    status = st.query_params.get("status", "").strip()
    if not room_code or not member_name or status not in [*STATUS_OPTIONS, CLEAR_STATUS]:
        st.query_params.pop("paint", None)
        return
    room = get_room(room_code)
    if not room or not any(member["name"] == member_name for member in room_members(room_code)):
        st.query_params.pop("paint", None)
        return
    windows = get_windows(room)
    changed = 0
    try:
        for group in payload.split(";"):
            if not group or ":" not in group or "-" not in group:
                continue
            day_string, range_part = group.split(":", 1)
            start_text, end_text = range_part.split("-", 1)
            selected_day = date.fromisoformat(day_string)
            start_minute = int(start_text)
            end_minute = int(end_text)
            for minute in range(start_minute, end_minute + 1, 15):
                if not (0 <= minute < 1440) or is_unavailable(minute_to_time(minute), windows):
                    continue
                if status == CLEAR_STATUS:
                    clear_availability_slot(room_code, member_name, selected_day, minute)
                else:
                    save_availability(room_code, member_name, selected_day, minute, minute + 15, status)
                changed += 1
    except (ValueError, TypeError):
        st.session_state["schedule_grid_notice"] = ("error", "드래그 입력을 처리하지 못했습니다. 다시 시도해 주세요.")
    else:
        if changed:
            st.session_state["schedule_grid_notice"] = ("success", f"{changed}개의 15분 칸을 변경했습니다.")
    for key in ("paint", "status"):
        st.query_params.pop(key, None)


def minute_to_time(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def time_choices(include_midnight_end: bool = False) -> list[str]:
    end = 1440 if include_midnight_end else 1425
    return [minute_to_time(minute) for minute in range(0, end + 1, 15)]


def time_to_minute(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def get_room(room_code: str) -> dict[str, str] | None:
    return next((room for room in read_rows(ROOMS_FILE) if room["room_code"] == room_code), None)


def room_members(room_code: str) -> list[dict[str, str]]:
    return [member for member in read_rows(MEMBERS_FILE) if member["room_code"] == room_code]


def get_windows(room: dict[str, str]) -> list[dict[str, str]]:
    try:
        values = json.loads(room.get("unavailable_windows", "[]"))
        return [window for window in values if "start" in window and "end" in window]
    except (json.JSONDecodeError, TypeError):
        return []


def is_unavailable(value: str, windows: list[dict[str, str]]) -> bool:
    minute = time_to_minute(value)
    for window in windows:
        start = time_to_minute(window["start"])
        end = time_to_minute(window["end"])
        if start < end and start <= minute < end:
            return True
        if start > end and (minute >= start or minute < end):
            return True
    return False


def dates_in_room(room: dict[str, str]) -> list[date]:
    first = date.fromisoformat(room["start_date"])
    last = date.fromisoformat(room["end_date"])
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def week_dates_in_room(room: dict[str, str], selected_date: date) -> list[date]:
    week_start = selected_date - timedelta(days=selected_date.weekday())
    room_start = date.fromisoformat(room["start_date"])
    room_end = date.fromisoformat(room["end_date"])
    first = max(week_start, room_start)
    last = min(week_start + timedelta(days=6), room_end)
    if first > last:
        return []
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def visible_schedule_minutes(windows: list[dict[str, str]]) -> list[int]:
    slots = list(range(0, 1440, 15))
    blocked = {
        minute
        for minute in slots
        if is_unavailable(minute_to_time(minute), windows)
    }
    first = 0
    last = len(slots) - 1
    while first <= last and slots[first] in blocked:
        first += 1
    while last >= first and slots[last] in blocked:
        last -= 1
    return slots[first : last + 1]


def entries_for_dates(
    room_code: str, dates: list[date]
) -> dict[tuple[str, str, str], str]:
    date_keys = {selected_date.isoformat() for selected_date in dates}
    return {
        (row["date"], row["member_name"], row["time"]): LEGACY_STATUS_MAP.get(
            row["status"], row["status"]
        )
        for row in read_rows(AVAILABILITY_FILE)
        if row["room_code"] == room_code and row["date"] in date_keys
    }


def entry_lookup(room_code: str, selected_date: date) -> dict[tuple[str, str], str]:
    return {
        (row["member_name"], row["time"]): LEGACY_STATUS_MAP.get(
            row["status"], row["status"]
        )
        for row in read_rows(AVAILABILITY_FILE)
        if row["room_code"] == room_code and row["date"] == selected_date.isoformat()
    }


def show_room_creation() -> None:
    st.subheader("새 합주 방 만들기")
    with st.form("create_room_form"):
        room_name = st.text_input("방 이름", placeholder="예: 토요일 밴드 합주")
        host_name = st.text_input("만든 사람 이름", placeholder="예: 민지")
        password_enabled = st.checkbox("방 비밀번호 설정", value=False)
        room_password = st.text_input(
            "방 비밀번호",
            type="password",
            max_chars=50,
            placeholder="비밀번호를 입력하세요",
            disabled=not password_enabled,
            help="설정하면 방 코드와 비밀번호를 모두 알아야 참여할 수 있습니다.",
        )
        date_col1, date_col2 = st.columns(2)
        start_date = date_col1.date_input("합주 시작일", value=date.today(), key="new_room_start")
        end_date = date_col2.date_input(
            "합주 종료일", value=date.today() + timedelta(days=13), key="new_room_end"
        )

        st.markdown("**방장이 미리 정하는 합주 불가 시간대**")
        st.caption("선택한 시간은 모든 멤버에게 일정 입력이 막히며 종합표에 운영 불가로 표시됩니다.")
        window1_enabled = st.checkbox("불가 시간대 1 사용", value=True)
        window1_cols = st.columns(2)
        window1_start = window1_cols[0].selectbox(
            "시작", time_choices(), index=0, key="new_window1_start"
        )
        window1_end = window1_cols[1].selectbox(
            "종료", time_choices(include_midnight_end=True), index=24, key="new_window1_end"
        )
        window2_enabled = st.checkbox("불가 시간대 2 사용", value=False)
        window2_cols = st.columns(2)
        window2_start = window2_cols[0].selectbox(
            "시작", time_choices(), index=88, key="new_window2_start"
        )
        window2_end = window2_cols[1].selectbox(
            "종료", time_choices(include_midnight_end=True), index=92, key="new_window2_end"
        )
        submitted = st.form_submit_button("방 만들기", type="primary", use_container_width=True)

    if submitted:
        room_name = room_name.strip()
        host_name = host_name.strip()
        if not room_name or not host_name:
            st.error("방 이름과 만든 사람 이름을 모두 입력해 주세요.")
            return
        if password_enabled and len(room_password) < 4:
            st.error("방 비밀번호는 4자 이상으로 설정해 주세요.")
            return
        if end_date < start_date:
            st.error("종료일은 시작일보다 빠를 수 없습니다.")
            return
        windows: list[dict[str, str]] = []
        if window1_enabled:
            if window1_start == window1_end:
                st.error("불가 시간대 1의 시작과 종료를 다르게 설정해 주세요.")
                return
            windows.append({"start": window1_start, "end": window1_end})
        if window2_enabled:
            if window2_start == window2_end:
                st.error("불가 시간대 2의 시작과 종료를 다르게 설정해 주세요.")
                return
            windows.append({"start": window2_start, "end": window2_end})

        existing_codes = {room["room_code"] for room in read_rows(ROOMS_FILE)}
        try:
            code = make_room_code(existing_codes)
            room = {
                "room_code": code,
                "room_name": room_name,
                "host_name": host_name,
                "password_hash": hash_password(room_password) if password_enabled else "",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "unavailable_windows": json.dumps(windows, ensure_ascii=False),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            save_room(room)
            save_member(code, host_name, "방장")
            set_room_session(code, host_name)
            st.success(f"방을 만들었습니다. 방 코드: **{code}**")
            st.rerun()
        except RuntimeError as error:
            st.error(str(error))


def show_join_room() -> None:
    st.subheader("초대 코드로 방 참여하기")
    with st.form("join_room_form"):
        code = st.text_input("6자리 방 코드", max_chars=6, placeholder="예: 038517")
        member_name = st.text_input("내 이름", placeholder="예: 지훈")
        room_password = st.text_input("방 비밀번호", type="password", placeholder="비밀번호가 설정된 방만 입력")
        submitted = st.form_submit_button("방 참여", type="primary", use_container_width=True)
    if submitted:
        normalized_code = code.strip()
        member_name = member_name.strip()
        if len(normalized_code) != 6 or not normalized_code.isdigit():
            st.error("방 코드는 숫자 6자리로 입력해 주세요.")
            return
        if not member_name:
            st.error("이름을 입력해 주세요.")
            return
        room = get_room(normalized_code)
        if not room:
            st.error("해당 코드의 방을 찾을 수 없습니다.")
            return
        if not verify_room_password(room, room_password):
            st.error("방 비밀번호가 맞지 않습니다.")
            return
        save_member(normalized_code, member_name)
        set_room_session(normalized_code, member_name)
        st.success(f"'{room['room_name']}' 방에 참여했습니다.")
        st.rerun()


def format_hour_label(minute: int) -> str:
    hour = minute // 60
    if minute % 60:
        return ""
    if hour == 0:
        return "오전 12시"
    if hour < 12:
        return f"오전 {hour}시"
    if hour == 12:
        return "오후 12시"
    return f"오후 {hour - 12}시"


def show_status_legend() -> None:
    items = "".join(
        f'<span class="schedule-legend-item"><i class="schedule-swatch" '
        f'style="background:{STATUS_COLORS[status]}"></i>'
        f"{html_escape(status)}</span>"
        for status in STATUS_OPTIONS
    )
    items += (
        '<span class="schedule-legend-item"><i class="schedule-swatch blocked"></i>'
        "합주 금지</span>"
    )
    st.markdown(f'<div class="schedule-legend">{items}</div>', unsafe_allow_html=True)


def render_editable_schedule_grid(
    room: dict[str, str],
    member_name: str,
    dates: list[date],
    minutes: list[int],
    windows: list[dict[str, str]],
    statuses: dict[tuple[str, str], str],
    selected_status: str,
) -> None:
    """HTML/JS grid: click or drag over cells, then send compact ranges back via query params."""
    import streamlit.components.v1 as components

    weekday_names = "월화수목금토일"
    date_json = json.dumps([d.isoformat() for d in dates], ensure_ascii=False)
    minute_json = json.dumps(minutes)
    blocked_json = json.dumps(
        {d.isoformat(): [m for m in minutes if is_unavailable(minute_to_time(m), windows)] for d in dates}
    )
    status_json = json.dumps(
        {f"{d.isoformat()}|{minute}": statuses.get((d.isoformat(), minute_to_time(minute)), "") for d in dates for minute in minutes},
        ensure_ascii=False,
    )
    colors_json = json.dumps(STATUS_COLORS, ensure_ascii=False)
    selected_json = json.dumps(selected_status, ensure_ascii=False)
    room_code_json = json.dumps(room["room_code"])
    member_json = json.dumps(member_name, ensure_ascii=False)
    clear_json = json.dumps(CLEAR_STATUS, ensure_ascii=False)

    rows_html = []
    for minute in minutes:
        cells = [f'<div class="time-cell">{html_escape(format_hour_label(minute) or "")}</div>']
        for selected_date in dates:
            key = f"{selected_date.isoformat()}|{minute}"
            status = statuses.get((selected_date.isoformat(), minute_to_time(minute)), "")
            blocked = is_unavailable(minute_to_time(minute), windows)
            color = STATUS_COLORS.get(status, "#ffffff") if not blocked else "#374151"
            cells.append(
                f'<div class="slot {"blocked" if blocked else ""}" data-date="{selected_date.isoformat()}" '
                f'data-minute="{minute}" style="background:{color};"></div>'
            )
        rows_html.append(f'<div class="grid-row">{"".join(cells)}</div>')

    headers = ['<div class="header-cell time-header">시간</div>']
    for selected_date in dates:
        headers.append(
            f'<div class="header-cell">{selected_date:%m/%d}<small>{weekday_names[selected_date.weekday()]}</small></div>'
        )

    html = f"""
    <style>
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
      .toolbar {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; align-items:center; }}
      .hint {{ font-size:12px; color:#64748b; margin-bottom:8px; }}
      .wrap {{ overflow:auto; max-width:100%; border:1px solid #cbd5e1; border-radius:8px; }}
      .grid {{ min-width: 520px; user-select:none; touch-action:none; }}
      .grid-row, .grid-header {{ display:grid; grid-template-columns:72px repeat({len(dates)}, minmax(62px, 1fr)); }}
      .header-cell {{ position:sticky; top:0; z-index:3; background:#f8fafc; border-right:1px solid #cbd5e1; border-bottom:1px solid #94a3b8; text-align:center; padding:5px 2px; font-weight:700; font-size:12px; }}
      .header-cell small {{ display:block; font-weight:500; color:#64748b; }}
      .time-cell {{ background:#f8fafc; border-right:1px solid #cbd5e1; border-bottom:1px solid #cbd5e1; height:18px; line-height:18px; font-size:10px; text-align:right; padding-right:5px; white-space:nowrap; }}
      .slot {{ height:18px; border-right:1px solid #d1d5db; border-bottom:1px solid #d1d5db; cursor:crosshair; }}
      .slot:hover {{ outline:2px solid #111827; outline-offset:-2px; position:relative; z-index:2; }}
      .slot.blocked {{ cursor:not-allowed; opacity:1; }}
      .slot.drag-selected {{ outline:2px solid #111827; outline-offset:-2px; filter:brightness(.92); }}
      .status-button {{ border:1px solid #94a3b8; background:#fff; border-radius:7px; padding:6px 9px; font-size:12px; cursor:pointer; }}
      .status-button.active {{ border:2px solid #111827; font-weight:700; }}
      .apply-button {{ border:0; background:#111827; color:white; border-radius:7px; padding:7px 12px; font-size:12px; cursor:pointer; }}
      @media (max-width:700px) {{ .grid-row, .grid-header {{ grid-template-columns:62px repeat({len(dates)}, minmax(56px, 1fr)); }} .slot,.time-cell {{height:17px}} .status-button {{padding:6px 7px}} }}
    </style>
    <div class="toolbar" id="toolbar"></div>
    <div class="hint">상태를 고른 뒤 한 칸씩 누르거나, 마우스/손가락으로 여러 칸을 드래그하세요. 드래그가 끝나면 자동으로 저장됩니다.</div>
    <div class="wrap"><div class="grid">
      <div class="grid-header">{"".join(headers)}</div>
      {"".join(rows_html)}
    </div></div>
    <script>
      const dates = {date_json};
      const minutes = {minute_json};
      const blocked = {blocked_json};
      const colors = {colors_json};
      const selectedStatus = {selected_json};
      const clearStatus = {clear_json};
      const roomCode = {room_code_json};
      const memberName = {member_json};
      const toolbar = document.getElementById('toolbar');
      const statuses = {status_json};
      let currentStatus = selectedStatus;
      const labels = Object.keys(colors);
      const symbols = {{'합주 완전 가능':'가능','합주 가능(애매)':'애매','합주 가능(불편)':'불편','합주 완전 불가':'불가'}};
      function addButton(label, value) {{
        const b = document.createElement('button'); b.className='status-button'; b.textContent=label;
        if (value===currentStatus) b.classList.add('active');
        b.onclick=()=>{{ currentStatus=value; document.querySelectorAll('.status-button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); }};
        toolbar.appendChild(b);
      }}
      labels.forEach(x=>addButton(symbols[x],x));
      addButton('지우기', clearStatus);
      const apply = document.createElement('button'); apply.className='apply-button'; apply.textContent='전체 적용';
      apply.title='선택한 상태를 이번 주 전체(합주 금지 제외)에 적용';
      apply.onclick=()=>{{
        const slots=[...document.querySelectorAll('.slot:not(.blocked)')];
        if(!confirm('이번 주의 합주 금지 시간을 제외한 모든 칸을 선택한 상태로 바꿀까요?')) return;
        slots.forEach(x=>x.classList.add('drag-selected')); submitSlots(slots);
      }};
      toolbar.appendChild(apply);
      let dragging=false, selected=new Set(), anchor=null;
      function cellKey(el) {{ return el.dataset.date+'|'+el.dataset.minute; }}
      function paintVisual(el) {{
        el.classList.add('drag-selected');
        if(currentStatus===clearStatus) el.style.background='#fff'; else el.style.background=colors[currentStatus];
      }}
      function addCell(el) {{ if(!el || el.classList.contains('blocked')) return; selected.add(cellKey(el)); paintVisual(el); }}
      function rangeSelect(a,b) {{
        if(!a || !b) return;
        const dateA=a.dataset.date, dateB=b.dataset.date;
        const minuteA=+a.dataset.minute, minuteB=+b.dataset.minute;
        const loDate=Math.min(dates.indexOf(dateA), dates.indexOf(dateB));
        const hiDate=Math.max(dates.indexOf(dateA), dates.indexOf(dateB));
        const loMinute=Math.min(minuteA, minuteB), hiMinute=Math.max(minuteA, minuteB);
        for(let di=loDate; di<=hiDate; di++) {{
          document.querySelectorAll(`.slot[data-date="${{dates[di]}}"]`).forEach(el=>{{
            const m=+el.dataset.minute; if(m>=loMinute&&m<=hiMinute) addCell(el);
          }});
        }}
      }}
      function submitSlots(elements) {{
        const all = elements ? [...elements] : [...document.querySelectorAll('.slot.drag-selected:not(.blocked)')];
        if(!all.length) return;
        const grouped={{}};
        all.forEach(el=>{{(grouped[el.dataset.date]??=[]).push(+el.dataset.minute);}});
        const ranges=[];
        Object.entries(grouped).forEach(([d,arr])=>{{arr.sort((a,b)=>a-b);let start=arr[0],prev=arr[0];for(let i=1;i<arr.length;i++){{if(arr[i]!==prev+15){{ranges.push(d+':'+start+'-'+prev);start=arr[i];}}prev=arr[i];}}ranges.push(d+':'+start+'-'+prev);}});
        const params=new URLSearchParams(window.top.location.search);
        params.set('room',roomCode); params.set('member',memberName); params.set('status',currentStatus); params.set('paint',ranges.join(';'));
        window.top.location.href=window.top.location.pathname+'?'+params.toString();
      }}
      document.querySelectorAll('.slot:not(.blocked)').forEach(el=>{{
        el.addEventListener('pointerdown',e=>{{ e.preventDefault(); dragging=true; selected.clear(); anchor=el; addCell(el); el.setPointerCapture?.(e.pointerId); }});
        el.addEventListener('pointerenter',e=>{{ if(dragging) rangeSelect(anchor,el); }});
        el.addEventListener('pointerup',e=>{{ if(dragging){{ dragging=false; submitSlots(); }} }});
      }});
      document.addEventListener('pointerup',()=>{{ if(dragging){{dragging=false;submitSlots();}} }});
    </script>
    """
    components.html(html, height=min(1900, 92 + len(minutes)*18), scrolling=False)


def render_schedule_grid(
    dates: list[date],
    minutes: list[int],
    windows: list[dict[str, str]],
    statuses: dict[tuple[str, str], str],
    titles: dict[tuple[str, str], str] | None = None,
) -> None:
    weekday_names = "월화수목금토일"
    title_lookup = titles or {}
    header_cells = "".join(
        f"<th scope='col'>{selected_date:%m/%d}<br>{weekday_names[selected_date.weekday()]}</th>"
        for selected_date in dates
    )
    rows: list[str] = []

    for minute in minutes:
        row_cells = [
            f"<th class='schedule-time' scope='row'>{format_hour_label(minute)}</th>"
        ]
        slot_time = minute_to_time(minute)
        for selected_date in dates:
            date_key = selected_date.isoformat()
            cell_key = (date_key, slot_time)
            if is_unavailable(slot_time, windows):
                row_cells.append(
                    "<td class='schedule-cell blocked' title='방장이 설정한 합주 금지 시간'>"
                    "<span></span></td>"
                )
                continue

            status = statuses.get(cell_key, "")
            color_class = STATUS_CLASSES.get(status, "empty")
            title = title_lookup.get(cell_key, status or "미입력")
            cell_content = (
                f"<span title='{html_escape(title, quote=True)}' "
                f"aria-label='{html_escape(title, quote=True)}'></span>"
            )
            row_cells.append(f"<td class='schedule-cell {color_class}'>{cell_content}</td>")
        rows.append(f"<tr>{''.join(row_cells)}</tr>")

    color_rules = "".join(
        f".schedule-cell.{STATUS_CLASSES[status]} {{ background: {color}; }}"
        for status, color in STATUS_COLORS.items()
    )
    style = """
    <style>
      .schedule-legend {
        display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
        margin: 4px 0 12px; font-size: 0.84rem;
      }
      .schedule-legend-item { display: inline-flex; align-items: center; gap: 6px; }
      .schedule-swatch {
        display: inline-block; width: 14px; height: 14px; border: 1px solid #6b7280;
        border-radius: 3px;
      }
      __STATUS_COLOR_RULES__
      .schedule-swatch.blocked, .schedule-cell.blocked { background: #374151; }
      .schedule-grid-wrap { overflow-x: auto; width: 100%; }
      table.schedule-grid {
        width: 100%; min-width: 520px; table-layout: fixed; border-collapse: collapse;
        background: #fff; font-size: 0.82rem;
      }
      .schedule-grid th, .schedule-grid td {
        border: 1px solid #6b7280; padding: 0; text-align: center;
      }
      .schedule-grid thead th {
        position: sticky; top: 0; z-index: 2; height: 42px;
        background: #f8fafc; color: #111827; font-weight: 700;
      }
      .schedule-grid th.schedule-time {
        width: 88px; min-width: 88px; padding: 0 8px; text-align: right;
        white-space: nowrap; background: #f8fafc; color: #374151; font-weight: 600;
      }
      .schedule-grid td.schedule-cell { height: 18px; min-width: 48px; }
      .schedule-grid td.schedule-cell.empty { background: #fff; }
      .schedule-grid td.schedule-cell.blocked { background: #374151; }
      .schedule-grid td.schedule-cell a, .schedule-grid td.schedule-cell span {
        display: block; width: 100%; height: 17px; min-height: 17px;
      }
      .schedule-grid td.schedule-cell a:hover {
        outline: 2px solid #111827; outline-offset: -2px; filter: brightness(0.92);
      }
      @media (max-width: 700px) {
        .schedule-grid th.schedule-time { width: 72px; min-width: 72px; }
        table.schedule-grid { min-width: 420px; }
      }
    </style>
    """.replace("__STATUS_COLOR_RULES__", color_rules)
    table = (
        '<div class="schedule-grid-wrap"><table class="schedule-grid">'
        f"<thead><tr><th class='schedule-time' scope='col'>시간</th>{header_cells}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
    st.markdown(style + table, unsafe_allow_html=True)


def apply_bulk_status(
    room: dict[str, str],
    member_name: str,
    dates: list[date],
    minutes: list[int],
    windows: list[dict[str, str]],
    status: str,
) -> None:
    entries = read_rows(AVAILABILITY_FILE)
    for selected_day in dates:
        day_string = selected_day.isoformat()
        for minute in minutes:
            slot_time = minute_to_time(minute)
            if is_unavailable(slot_time, windows):
                continue
            found = False
            for entry in entries:
                if (
                    entry["room_code"] == room["room_code"]
                    and entry["member_name"] == member_name
                    and entry["date"] == day_string
                    and entry["time"] == slot_time
                ):
                    entry["status"] = status
                    found = True
                    break
            if not found:
                entries.append({
                    "room_code": room["room_code"],
                    "member_name": member_name,
                    "date": day_string,
                    "time": slot_time,
                    "status": status,
                })
    write_rows(AVAILABILITY_FILE, AVAILABILITY_FIELDS, entries)


def show_schedule_input(
    room: dict[str, str],
    member_name: str,
    selected_date: date,
    windows: list[dict[str, str]],
) -> None:
    st.subheader("내 일정 입력")
    notice = st.session_state.pop("schedule_grid_notice", None)
    if notice:
        getattr(st, notice[0])(notice[1])

    dates = week_dates_in_room(room, selected_date)
    minutes = visible_schedule_minutes(windows)
    if not dates or not minutes:
        st.info("표시할 날짜 또는 시간이 없습니다.")
        return

    selected_status = STATUS_OPTIONS[0]
    st.caption(
        f"{dates[0]:%Y.%m.%d}–{dates[-1]:%Y.%m.%d} 주간 표입니다. "
        "표 위의 상태 버튼을 고른 뒤 칸을 누르거나 드래그하세요."
    )
    show_status_legend()
    bulk_col1, bulk_col2 = st.columns(2)
    with bulk_col1:
        if st.button("합주 금지 제외 전부 합주 완전 가능", use_container_width=True, key=f"bulk_yes_{room['room_code']}_{member_name}_{selected_date}"):
            apply_bulk_status(room, member_name, dates, minutes, windows, STATUS_OPTIONS[0])
            st.rerun()
    with bulk_col2:
        if st.button("합주 금지 제외 전부 합주 완전 불가", use_container_width=True, key=f"bulk_no_{room['room_code']}_{member_name}_{selected_date}"):
            apply_bulk_status(room, member_name, dates, minutes, windows, STATUS_OPTIONS[3])
            st.rerun()
    if minutes and (minutes[0] > 0 or minutes[-1] < 1425):
        st.caption("하루의 시작이나 끝에 붙은 합주 금지 시간은 표에서 생략했습니다.")
    stored_entries = entries_for_dates(room["room_code"], dates)
    statuses = {
        (date_key, slot_time): status
        for (date_key, saved_member, slot_time), status in stored_entries.items()
        if saved_member == member_name
    }
    render_editable_schedule_grid(
        room,
        member_name,
        dates,
        minutes,
        windows,
        statuses,
        selected_status,
    )


def show_overview(
    room: dict[str, str],
    members: list[dict[str, str]],
    selected_date: date,
    windows: list[dict[str, str]],
) -> None:
    st.subheader("방 전체 합주 가능도")
    st.caption("칸의 색은 입력된 응답 중 가장 제한적인 상태를 나타냅니다. 응답 수는 칸에 마우스를 올려 확인하세요.")
    if not members:
        st.info("아직 참여한 멤버가 없습니다.")
        return

    dates = week_dates_in_room(room, selected_date)
    minutes = visible_schedule_minutes(windows)
    if not dates or not minutes:
        st.info("표시할 날짜 또는 시간이 없습니다.")
        return

    stored_entries = entries_for_dates(room["room_code"], dates)
    statuses: dict[tuple[str, str], str] = {}
    titles: dict[tuple[str, str], str] = {}
    ideal_slots = 0
    pending_slots = 0
    unavailable_slots = 0

    for selected_day in dates:
        date_key = selected_day.isoformat()
        for minute in minutes:
            slot_time = minute_to_time(minute)
            cell_key = (date_key, slot_time)
            if is_unavailable(slot_time, windows):
                unavailable_slots += 1
                titles[cell_key] = "방장이 설정한 합주 금지 시간"
                continue

            values = [
                stored_entries.get((date_key, member["name"], slot_time))
                for member in members
            ]
            received = [value for value in values if value in STATUS_OPTIONS]
            missing = len(members) - len(received)
            if missing:
                pending_slots += 1
            if not received:
                titles[cell_key] = "응답 대기"
                continue

            worst = max(received, key=STATUS_OPTIONS.index)
            statuses[cell_key] = worst
            titles[cell_key] = f"{worst} · {len(received)}/{len(members)}명 응답"
            if missing == 0 and worst == STATUS_OPTIONS[0]:
                ideal_slots += 1

    ideal_col, pending_col, unavailable_col = st.columns(3)
    ideal_col.metric(
        "이번 주 전원 합주 가능",
        f"{ideal_slots * 15 // 60}시간 {ideal_slots * 15 % 60}분",
    )
    pending_col.metric("이번 주 응답 대기", f"{pending_slots}칸")
    unavailable_col.metric("이번 주 합주 금지", f"{unavailable_slots}칸")
    show_status_legend()
    render_schedule_grid(
        dates, minutes, windows, statuses, titles
    )


def show_member_schedule(
    room: dict[str, str],
    members: list[dict[str, str]],
    selected_date: date,
    windows: list[dict[str, str]],
) -> None:
    st.subheader("멤버별 일정")
    selected_member = st.selectbox(
        "일정을 확인할 멤버",
        [member["name"] for member in members],
        key="member_schedule_choice",
    )
    dates = week_dates_in_room(room, selected_date)
    minutes = visible_schedule_minutes(windows)
    if not dates or not minutes:
        st.info("표시할 날짜 또는 시간이 없습니다.")
        return

    stored_entries = entries_for_dates(room["room_code"], dates)
    statuses = {
        (date_key, slot_time): status
        for (date_key, saved_member, slot_time), status in stored_entries.items()
        if saved_member == selected_member and status in STATUS_OPTIONS
    }
    titles = {
        key: status
        for key, status in statuses.items()
    }
    show_status_legend()
    bulk_col1, bulk_col2 = st.columns(2)
    with bulk_col1:
        if st.button("합주 금지 제외 전부 합주 완전 가능", use_container_width=True, key=f"bulk_yes_{room['room_code']}_{member_name}_{selected_date}"):
            apply_bulk_status(room, member_name, dates, minutes, windows, STATUS_OPTIONS[0])
            st.rerun()
    with bulk_col2:
        if st.button("합주 금지 제외 전부 합주 완전 불가", use_container_width=True, key=f"bulk_no_{room['room_code']}_{member_name}_{selected_date}"):
            apply_bulk_status(room, member_name, dates, minutes, windows, STATUS_OPTIONS[3])
            st.rerun()
    if minutes and (minutes[0] > 0 or minutes[-1] < 1425):
        st.caption("하루의 시작이나 끝에 붙은 합주 금지 시간은 표에서 생략했습니다.")
    render_schedule_grid(
        dates, minutes, windows, statuses, titles
    )


def show_host_settings(room: dict[str, str], member_name: str, windows: list[dict[str, str]]) -> None:
    st.subheader("방장 설정")
    st.caption("불가 시간대를 바꾸면 해당 시간은 모든 멤버에게 일정 입력이 제한됩니다.")
    with st.form("host_windows_form"):
        window_count = st.number_input(
            "사용할 불가 시간대 수", min_value=0, max_value=2, value=len(windows), step=1
        )
        options = time_choices()
        end_options = time_choices(include_midnight_end=True)
        selected_windows: list[dict[str, str]] = []
        for index in range(int(window_count)):
            existing = windows[index] if index < len(windows) else {"start": "00:00", "end": "06:00"}
            cols = st.columns(2)
            start_index = options.index(existing["start"]) if existing["start"] in options else 0
            end_index = end_options.index(existing["end"]) if existing["end"] in end_options else 24
            start = cols[0].selectbox(
                f"시간대 {index + 1} 시작", options, index=start_index, key=f"host_start_{index}"
            )
            end = cols[1].selectbox(
                f"시간대 {index + 1} 종료", end_options, index=end_index, key=f"host_end_{index}"
            )
            selected_windows.append({"start": start, "end": end})
        submitted = st.form_submit_button("불가 시간대 저장", type="primary")
    if submitted:
        if any(window["start"] == window["end"] for window in selected_windows):
            st.error("시작과 종료가 같은 시간대가 있습니다. 시간을 다르게 설정해 주세요.")
            return
        room["unavailable_windows"] = json.dumps(selected_windows, ensure_ascii=False)
        try:
            save_room(room)
            st.success("방 설정을 저장했습니다.")
            st.rerun()
        except RuntimeError as error:
            st.error(str(error))


def show_rejoin_room() -> None:
    if st.session_state.get("room_code") and st.session_state.get("member_name"):
        return
    room_code = st.query_params.get("room", "").strip()
    member_name = st.query_params.get("member", "").strip()
    if not room_code or not member_name:
        return
    room = get_room(room_code)
    if not room or not any(member["name"] == member_name for member in room_members(room_code)):
        return
    if not room_password_enabled(room):
        set_room_session(room_code, member_name)
        return
    st.info(f"이전에 **{room['room_name']}** 방({room_code})에 참여했던 기록이 있습니다.")
    with st.form("restore_room_form"):
        password = st.text_input("방 비밀번호", type="password")
        if st.form_submit_button("이 방으로 다시 들어가기", type="primary", use_container_width=True):
            if verify_room_password(room, password):
                set_room_session(room_code, member_name)
                st.rerun()
            else:
                st.error("방 비밀번호가 맞지 않습니다.")


def show_active_room() -> None:
    room_code = st.session_state.get("room_code", "")
    member_name = st.session_state.get("member_name", "")
    room = get_room(room_code) if room_code else None
    if not room or not member_name:
        st.info("방을 만들거나 초대 코드로 참여하면 일정 관리 화면이 여기에 표시됩니다.")
        return

    members = room_members(room_code)
    if not any(member["name"] == member_name for member in members):
        st.warning("현재 멤버 정보를 찾을 수 없습니다. 방 코드로 다시 참여해 주세요.")
        return
    windows = get_windows(room)
    room_start = date.fromisoformat(room["start_date"])
    room_end = date.fromisoformat(room["end_date"])

    title_col, action_col = st.columns([4, 1])
    title_col.subheader(room["room_name"])
    title_col.caption(
        f"방 코드 **{room_code}** · 내 이름 **{member_name}** · "
        f"{room_start.strftime('%Y.%m.%d')} – {room_end.strftime('%Y.%m.%d')} · 멤버 {len(members)}명"
    )
    if action_col.button("방 나가기", use_container_width=True):
        clear_room_session()
        st.rerun()
    st.info(f"초대할 멤버에게 방 코드 **{room_code}**를 공유하세요.")

    selected_date = st.date_input(
        "확인할 날짜",
        value=max(room_start, min(date.today(), room_end)),
        min_value=room_start,
        max_value=room_end,
        key=f"room_date_{room_code}",
    )
    tab_names = ["내 일정 입력", "전체 가능도", "멤버별 일정"]
    is_host = member_name == room["host_name"]
    if is_host:
        tab_names.append("방장 설정")
    tabs = st.tabs(tab_names)
    with tabs[0]:
        show_schedule_input(room, member_name, selected_date, windows)
    with tabs[1]:
        show_overview(room, members, selected_date, windows)
    with tabs[2]:
        show_member_schedule(room, members, selected_date, windows)
    if is_host:
        with tabs[3]:
            show_host_settings(room, member_name, windows)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    ensure_data_files()
    migrate_legacy_statuses()
    restore_room_from_query()
    apply_paint_ranges_from_query()
    st.title(APP_TITLE)
    st.caption("멤버들의 15분 단위 일정을 모아 다 같이 합주하기 좋은 시간을 찾아보세요.")

    show_rejoin_room()
    create_tab, join_tab = st.tabs(["방 만들기", "방 참여"])
    with create_tab:
        show_room_creation()
    with join_tab:
        show_join_room()

    st.divider()
    show_active_room()
    st.caption("프로토타입 데이터는 프로젝트의 data 폴더에 CSV 파일로 저장됩니다.")


if __name__ == "__main__":
    main()

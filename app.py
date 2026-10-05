from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta
from typing import Any

import streamlit as st
from supabase import Client, create_client

APP_TITLE = "합주기가 됩시다 합"
APP_URL = "https://lets-be-hapjugi.streamlit.app/"

STATUS_OPTIONS = [
    "합주 완전 가능",
    "합주 가능(애매)",
    "합주 가능(불편)",
    "합주 완전 불가",
]
CLEAR_STATUS = "입력 지우기"
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


def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_PUBLISHABLE_KEY"]
    client = create_client(url, key)

    if not getattr(st.user, "is_logged_in", False):
        return client

    try:
        id_token = st.user.tokens["id"]
        if id_token:
            response = client.auth.sign_in_with_id_token(
                {"provider": "google", "token": id_token}
            )
            if getattr(response, "session", None):
                return client
    except Exception as exc:
        st.error(f"Supabase 로그인 연결에 실패했습니다: {exc}")
        st.stop()

    return client


def require_login() -> None:
    if not getattr(st.user, "is_logged_in", False):
        st.title(APP_TITLE)
        st.caption("멤버들의 15분 단위 일정을 모아 다 같이 합주하기 좋은 시간을 찾아보세요.")
        st.info("일정을 저장하고 새로고침 후에도 내 방과 내 일정을 찾으려면 Google 로그인이 필요합니다.")
        st.button("Google로 로그인", type="primary", use_container_width=True, on_click=st.login)
        st.stop()


def current_user_id() -> str:
    # Supabase Auth session is established in get_supabase().
    response = SUPABASE.auth.get_user()
    if not response.user:
        st.error("로그인 정보를 확인하지 못했습니다. 다시 로그인해 주세요.")
        st.stop()
    return response.user.id


def current_user_name() -> str:
    user = st.user.to_dict()
    return str(user.get("name") or user.get("email", "").split("@")[0] or "사용자")


def minute_to_time(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def time_choices(include_midnight_end: bool = False) -> list[str]:
    end = 1440 if include_midnight_end else 1425
    return [minute_to_time(m) for m in range(0, end + 1, 15)]


def time_to_minute(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def get_windows(room: dict[str, Any]) -> list[dict[str, str]]:
    value = room.get("unavailable_windows") or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [w for w in value if isinstance(w, dict) and "start" in w and "end" in w]


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


def week_dates(room: dict[str, Any], selected_date: date) -> list[date]:
    room_start = date.fromisoformat(str(room["start_date"]))
    room_end = date.fromisoformat(str(room["end_date"]))
    week_start = selected_date - timedelta(days=selected_date.weekday())
    first = max(week_start, room_start)
    last = min(week_start + timedelta(days=6), room_end)
    if first > last:
        return []
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def visible_minutes(windows: list[dict[str, str]]) -> list[int]:
    slots = list(range(0, 1440, 15))
    blocked = {m for m in slots if is_unavailable(minute_to_time(m), windows)}
    first, last = 0, len(slots) - 1
    while first <= last and slots[first] in blocked:
        first += 1
    while last >= first and slots[last] in blocked:
        last -= 1
    return slots[first:last + 1]


def format_hour_label(minute: int) -> str:
    if minute % 60:
        return ""
    hour = minute // 60
    if hour == 0:
        return "오전 12시"
    if hour < 12:
        return f"오전 {hour}시"
    if hour == 12:
        return "오후 12시"
    return f"오후 {hour - 12}시"


def make_room_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def db_rooms_for_user(user_id: str) -> list[dict[str, Any]]:
    memberships = (
        SUPABASE.table("room_members")
        .select("room_id,name,role")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    if not memberships:
        return []
    room_ids = [m["room_id"] for m in memberships]
    rooms = (
        SUPABASE.table("rooms")
        .select("id,room_code,room_name,host_id,start_date,end_date,unavailable_windows,created_at")
        .in_("id", room_ids)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    by_id = {m["room_id"]: m for m in memberships}
    for room in rooms:
        room["my_membership"] = by_id.get(room["id"], {})
    return rooms


def get_room(room_id: str) -> dict[str, Any] | None:
    result = (
        SUPABASE.table("rooms")
        .select("id,room_code,room_name,host_id,start_date,end_date,unavailable_windows,created_at")
        .eq("id", room_id)
        .maybe_single()
        .execute()
    )
    return result.data


def get_members(room_id: str) -> list[dict[str, Any]]:
    return (
        SUPABASE.table("room_members")
        .select("id,user_id,name,role,joined_at")
        .eq("room_id", room_id)
        .order("joined_at")
        .execute()
        .data
        or []
    )


def get_availability(room_id: str, dates: list[date]) -> list[dict[str, Any]]:
    if not dates:
        return []
    start, end = dates[0].isoformat(), dates[-1].isoformat()
    return (
        SUPABASE.table("availability")
        .select("id,user_id,date,time,status")
        .eq("room_id", room_id)
        .gte("date", start)
        .lte("date", end)
        .execute()
        .data
        or []
    )


def upsert_slot(room_id: str, user_id: str, selected_date: date, minute: int, status: str) -> None:
    SUPABASE.table("availability").upsert(
        {
            "room_id": room_id,
            "user_id": user_id,
            "date": selected_date.isoformat(),
            "time": minute_to_time(minute),
            "status": status,
        },
        on_conflict="room_id,user_id,date,time",
    ).execute()


def clear_slot(room_id: str, user_id: str, selected_date: date, minute: int) -> None:
    SUPABASE.table("availability").delete().match(
        {
            "room_id": room_id,
            "user_id": user_id,
            "date": selected_date.isoformat(),
            "time": minute_to_time(minute),
        }
    ).execute()


def bulk_set(
    room_id: str,
    user_id: str,
    dates: list[date],
    minutes: list[int],
    windows: list[dict[str, str]],
    status: str,
    existing: set[tuple[str, str]],
) -> None:
    rows = []
    for selected_date in dates:
        for minute in minutes:
            slot = minute_to_time(minute)
            if is_unavailable(slot, windows):
                continue
            key = (selected_date.isoformat(), slot)
            if key in existing:
                continue
            rows.append(
                {
                    "room_id": room_id,
                    "user_id": user_id,
                    "date": selected_date.isoformat(),
                    "time": slot,
                    "status": status,
                }
            )
    if rows:
        SUPABASE.table("availability").upsert(
            rows,
            on_conflict="room_id,user_id,date,time",
        ).execute()


def create_room(room_name: str, display_name: str, password: str, start: date, end: date, windows: list[dict[str, str]]) -> dict[str, Any]:
    code = make_room_code()
    password_hash_value = None
    if password:
        import bcrypt
        password_hash_value = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

    result = SUPABASE.rpc(
        "create_room",
        {
            "p_room_code": code,
            "p_room_name": room_name,
            "p_host_name": display_name,
            "p_start_date": start.isoformat(),
            "p_end_date": end.isoformat(),
            "p_password_hash": password_hash_value,
        },
    ).execute()

    room_id = result.data[0] if isinstance(result.data, list) else result.data
    if not room_id:
        raise RuntimeError("방 생성에 실패했습니다.")

    SUPABASE.table("rooms").update(
        {"unavailable_windows": windows}
    ).eq("id", room_id).execute()

    room = get_room(str(room_id))
    if not room:
        raise RuntimeError("방 생성 후 방 정보를 불러오지 못했습니다.")
    return room


def lookup_room_by_code(code: str) -> dict[str, Any] | None:
    result = SUPABASE.rpc("lookup_room", {"p_room_code": code}).execute()
    if not result.data:
        return None
    return result.data[0] if isinstance(result.data, list) else result.data


def join_room(code: str, password: str, display_name: str) -> dict[str, Any]:
    result = SUPABASE.rpc(
        "join_room",
        {
            "p_room_code": code,
            "p_name": display_name,
            "p_password": password or None,
        },
    ).execute()
    room_id = result.data[0] if isinstance(result.data, list) else result.data
    if not room_id:
        raise RuntimeError("방 참여에 실패했습니다.")
    room = get_room(str(room_id))
    if not room:
        raise RuntimeError("방 참여 후 방 정보를 불러오지 못했습니다.")
    return room


def show_status_legend() -> None:
    items = "".join(
        f'<span class="legend-item"><i style="background:{STATUS_COLORS[s]}"></i>{s}</span>'
        for s in STATUS_OPTIONS
    )
    items += '<span class="legend-item"><i class="blocked-swatch"></i>합주 금지</span>'
    st.markdown(f'<div class="legend">{items}</div>', unsafe_allow_html=True)


def render_readonly_grid(dates, minutes, windows, statuses, titles=None) -> None:
    weekday = "월화수목금토일"
    titles = titles or {}
    headers = "".join(
        f"<th>{d:%m/%d}<br>{weekday[d.weekday()]}</th>" for d in dates
    )
    rows = []
    for minute in minutes:
        cells = [f'<th class="time">{format_hour_label(minute)}</th>']
        slot = minute_to_time(minute)
        for d in dates:
            key = (d.isoformat(), slot)
            if is_unavailable(slot, windows):
                cells.append('<td class="cell blocked" title="방장이 설정한 합주 금지 시간"></td>')
            else:
                status = statuses.get(key, "")
                cls = STATUS_CLASSES.get(status, "empty")
                title = titles.get(key, status or "미입력")
                cells.append(f'<td class="cell {cls}" title="{title}"></td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    st.markdown(
        """
        <style>
        .grid-wrap{overflow-x:auto;width:100%;}.grid{border-collapse:collapse;width:100%;min-width:520px;table-layout:fixed}
        .grid th,.grid td{border:1px solid #6b7280;padding:0;text-align:center}.grid thead th{height:40px;background:#f8fafc}
        .grid .time{width:86px;min-width:86px;text-align:right;padding-right:8px;background:#f8fafc;color:#374151}
        .grid .cell{height:18px}.grid .empty{background:#fff}.grid .blocked{background:#374151}
        .grid .fully-available{background:#16a34a}.grid .maybe-available{background:#facc15}.grid .uncomfortable{background:#f97316}.grid .unavailable{background:#ef4444}
        .legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin:4px 0 12px;font-size:.84rem}.legend-item{display:inline-flex;align-items:center;gap:6px}.legend-item i{display:inline-block;width:14px;height:14px;border:1px solid #6b7280;border-radius:3px}.blocked-swatch{background:#374151}
        </style>
        """ + f'<div class="grid-wrap"><table class="grid"><thead><tr><th class="time">시간</th>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def render_editable_grid(room, user_id, dates, minutes, windows, statuses, selected_status):
    weekday = "월화수목금토일"
    columns = [0.8] + [1.0] * len(dates)
    header = st.columns(columns, gap=None)
    header[0].markdown("**시간**")
    for c, d in zip(header[1:], dates):
        c.markdown(f"**{d:%m/%d}**<br>{weekday[d.weekday()]}", unsafe_allow_html=True)

    st.markdown(
        """
        <style>
        div[class*="slotbtn_"]{padding:0!important;margin:0!important}
        div[class*="slotbtn_"] button{height:20px!important;min-height:20px!important;padding:0!important;border-radius:0!important;border:1px solid #6b7280!important}
        div[class*="slotbtn_"] button p{margin:0!important;font-size:0!important}
        </style>
        """,
        unsafe_allow_html=True,
    )

    for minute in minutes:
        row = st.columns(columns, gap=None)
        row[0].markdown(format_hour_label(minute) or "&nbsp;", unsafe_allow_html=True)
        slot = minute_to_time(minute)
        for col, d in zip(row[1:], dates):
            key = (d.isoformat(), slot)
            status = statuses.get(key, "")
            blocked = is_unavailable(slot, windows)
            cls = STATUS_CLASSES.get(status, "empty").replace("-", "_")
            if blocked:
                cls = "blocked"
            label = " "
            with col.container(key=f"slotbtn_{room['id']}_{d:%Y%m%d}_{minute}_{cls}"):
                clicked = st.button(
                    label,
                    key=f"slot_{room['id']}_{d:%Y%m%d}_{minute}",
                    disabled=blocked,
                    use_container_width=True,
                    help=f"{d:%m/%d} {slot} · {'합주 금지' if blocked else status or '미입력'}",
                )
            if clicked:
                try:
                    if selected_status == CLEAR_STATUS:
                        clear_slot(room["id"], user_id, d, minute)
                    else:
                        upsert_slot(room["id"], user_id, d, minute, selected_status)
                    st.rerun()
                except Exception as exc:
                    st.error(f"일정 저장에 실패했습니다: {exc}")


def show_room_creation(user_id: str):
    st.subheader("새 합주 방 만들기")
    with st.form("create_room_form"):
        room_name = st.text_input("방 이름", placeholder="예: 토요일 밴드 합주")
        default_name = current_user_name()
        host_name = st.text_input("내 이름", value=default_name)
        password = st.text_input("방 비밀번호 (선택)", type="password", help="비워 두면 비밀번호 없이 방 코드만으로 참여할 수 있습니다.")
        c1, c2 = st.columns(2)
        start = c1.date_input("합주 시작일", date.today())
        end = c2.date_input("합주 종료일", date.today() + timedelta(days=13))
        st.markdown("**방장이 미리 정하는 합주 불가 시간대**")
        st.caption("선택한 시간은 모든 멤버에게 일정 입력이 막힙니다.")
        e1 = st.checkbox("불가 시간대 1 사용", True)
        c1, c2 = st.columns(2)
        s1 = c1.selectbox("시작", time_choices(), index=0)
        t1 = c2.selectbox("종료", time_choices(True), index=24)
        e2 = st.checkbox("불가 시간대 2 사용", False)
        c1, c2 = st.columns(2)
        s2 = c1.selectbox("시작", time_choices(), index=88)
        t2 = c2.selectbox("종료", time_choices(True), index=92)
        submitted = st.form_submit_button("방 만들기", type="primary", use_container_width=True)
    if not submitted:
        return
    room_name, host_name = room_name.strip(), host_name.strip()
    if not room_name or not host_name:
        st.error("방 이름과 내 이름을 입력해 주세요.")
        return
    if end < start:
        st.error("종료일은 시작일보다 빠를 수 없습니다.")
        return
    windows = []
    for enabled, s, e in ((e1, s1, t1), (e2, s2, t2)):
        if enabled:
            if s == e:
                st.error("불가 시간대의 시작과 종료를 다르게 설정해 주세요.")
                return
            windows.append({"start": s, "end": e})
    try:
        created = create_room(room_name, host_name, password.strip(), start, end, windows)
        st.session_state["active_room_id"] = created["id"]
        st.success(f"방을 만들었습니다. 방 코드: **{created['room_code']}**")
        st.rerun()
    except Exception as exc:
        st.error(f"방을 만들지 못했습니다: {exc}")


def show_join_room():
    st.subheader("초대 코드로 방 참여하기")
    with st.form("join_room_form"):
        code = st.text_input("6자리 방 코드", max_chars=6, placeholder="예: 038517")
        password = st.text_input("방 비밀번호", type="password", help="방장이 비밀번호를 설정하지 않았다면 비워 두세요.")
        name = st.text_input("내 이름", value=current_user_name())
        submitted = st.form_submit_button("방 참여", type="primary", use_container_width=True)
    if not submitted:
        return
    code, name = code.strip(), name.strip()
    if len(code) != 6 or not code.isdigit():
        st.error("방 코드는 숫자 6자리로 입력해 주세요.")
        return
    if not name:
        st.error("내 이름을 입력해 주세요.")
        return
    try:
        room = lookup_room_by_code(code)
        if not room:
            st.error("해당 코드의 방을 찾을 수 없습니다.")
            return
        joined = join_room(code, password.strip(), name)
        st.session_state["active_room_id"] = joined["id"]
        st.success(f"'{room['room_name']}' 방에 참여했습니다.")
        st.rerun()
    except Exception:
        st.error("방 코드 또는 비밀번호가 맞지 않습니다.")


def show_schedule_input(room, user_id, selected_date, windows):
    st.subheader("내 일정 입력")
    dates = week_dates(room, selected_date)
    minutes = visible_minutes(windows)
    if not dates or not minutes:
        st.info("표시할 날짜 또는 시간이 없습니다.")
        return
    selected_status = st.radio(
        "입력할 상태",
        [*STATUS_OPTIONS, CLEAR_STATUS],
        horizontal=True,
        key=f"paint_status_{room['id']}",
    )
    st.caption("상태를 고른 뒤 원하는 15분 칸을 누르세요. 이미 입력된 칸도 선택한 상태로 덮어씁니다.")
    show_status_legend()
    st.markdown("**미선택 칸에 대해:**")
    b1, b2 = st.columns(2)
    if b1.button("합주 완전 가능", use_container_width=True, key=f"bulk_yes_{room['id']}"):
        try:
            rows = get_availability(room["id"], dates)
            mine = {(str(r["date"]), str(r["time"])[:5]) for r in rows if r["user_id"] == user_id}
            bulk_set(room["id"], user_id, dates, minutes, windows, STATUS_OPTIONS[0], mine)
            st.rerun()
        except Exception as exc:
            st.error(f"일괄 입력에 실패했습니다: {exc}")
    if b2.button("합주 완전 불가", use_container_width=True, key=f"bulk_no_{room['id']}"):
        try:
            rows = get_availability(room["id"], dates)
            mine = {(str(r["date"]), str(r["time"])[:5]) for r in rows if r["user_id"] == user_id}
            bulk_set(room["id"], user_id, dates, minutes, windows, STATUS_OPTIONS[3], mine)
            st.rerun()
        except Exception as exc:
            st.error(f"일괄 입력에 실패했습니다: {exc}")
    st.caption("위 일괄 입력은 이미 상태가 들어간 칸은 건드리지 않고, 미선택 칸만 채웁니다. 합주 금지 시간은 제외됩니다.")

    rows = get_availability(room["id"], dates)
    statuses = {
        (str(r["date"]), str(r["time"])[:5]): r["status"]
        for r in rows if r["user_id"] == user_id
    }
    render_editable_grid(room, user_id, dates, minutes, windows, statuses, selected_status)


def show_overview(room, members, selected_date, windows):
    st.subheader("방 전체 합주 가능도")
    dates = week_dates(room, selected_date)
    minutes = visible_minutes(windows)
    if not dates or not minutes:
        st.info("표시할 날짜 또는 시간이 없습니다.")
        return
    rows = get_availability(room["id"], dates)
    lookup = {(str(r["date"]), str(r["user_id"]), str(r["time"])[:5]): r["status"] for r in rows}
    statuses, titles = {}, {}
    ideal = pending = unavailable = 0
    for d in dates:
        dk = d.isoformat()
        for minute in minutes:
            slot = minute_to_time(minute)
            key = (dk, slot)
            if is_unavailable(slot, windows):
                unavailable += 1
                titles[key] = "방장이 설정한 합주 금지 시간"
                continue
            values = [lookup.get((dk, str(m["user_id"]), slot)) for m in members]
            received = [v for v in values if v in STATUS_OPTIONS]
            missing = len(members) - len(received)
            if missing:
                pending += 1
            if not received:
                titles[key] = "응답 대기"
                continue
            worst = max(received, key=STATUS_OPTIONS.index)
            statuses[key] = worst
            titles[key] = f"{worst} · {len(received)}/{len(members)}명 응답"
            if missing == 0 and worst == STATUS_OPTIONS[0]:
                ideal += 1
    c1, c2, c3 = st.columns(3)
    c1.metric("이번 주 전원 합주 가능", f"{ideal * 15 // 60}시간 {ideal * 15 % 60}분")
    c2.metric("이번 주 응답 대기", f"{pending}칸")
    c3.metric("이번 주 합주 금지", f"{unavailable}칸")
    show_status_legend()
    render_readonly_grid(dates, minutes, windows, statuses, titles)


def show_member_schedule(room, members, selected_date, windows):
    st.subheader("멤버별 일정")
    names = [m["name"] for m in members]
    if not names:
        return
    name = st.selectbox("일정을 확인할 멤버", names, key=f"member_choice_{room['id']}")
    member = next(m for m in members if m["name"] == name)
    dates = week_dates(room, selected_date)
    minutes = visible_minutes(windows)
    rows = get_availability(room["id"], dates)
    statuses = {
        (str(r["date"]), str(r["time"])[:5]): r["status"]
        for r in rows if r["user_id"] == member["user_id"]
    }
    show_status_legend()
    render_readonly_grid(dates, minutes, windows, statuses)


def show_host_settings(room, windows):
    st.subheader("방장 설정")
    with st.form(f"host_settings_{room['id']}"):
        count = st.number_input("사용할 불가 시간대 수", 0, 2, len(windows), 1)
        options = time_choices()
        end_options = time_choices(True)
        selected = []
        for i in range(int(count)):
            existing = windows[i] if i < len(windows) else {"start": "00:00", "end": "06:00"}
            a, b = st.columns(2)
            s = a.selectbox(f"시간대 {i + 1} 시작", options, index=options.index(existing["start"]) if existing["start"] in options else 0, key=f"hs_{room['id']}_{i}")
            e = b.selectbox(f"시간대 {i + 1} 종료", end_options, index=end_options.index(existing["end"]) if existing["end"] in end_options else 24, key=f"he_{room['id']}_{i}")
            selected.append({"start": s, "end": e})
        submitted = st.form_submit_button("불가 시간대 저장", type="primary")
    if submitted:
        if any(w["start"] == w["end"] for w in selected):
            st.error("시작과 종료가 같은 시간대가 있습니다.")
            return
        try:
            SUPABASE.table("rooms").update({"unavailable_windows": selected}).eq("id", room["id"]).execute()
            st.success("방 설정을 저장했습니다.")
            st.rerun()
        except Exception as exc:
            st.error(f"방 설정 저장에 실패했습니다: {exc}")


def show_my_rooms(user_id: str):
    rooms = db_rooms_for_user(user_id)
    if not rooms:
        st.info("아직 참여한 합주 방이 없습니다. 방을 만들거나 초대 코드로 참여해 주세요.")
        return None
    labels = {
        r["id"]: f"{r['room_name']} · 코드 {r['room_code']} · 내 역할 {r['my_membership'].get('role', '회원')}"
        for r in rooms
    }
    ids = [r["id"] for r in rooms]
    current = st.session_state.get("active_room_id")
    default = ids.index(current) if current in ids else 0
    selected = st.selectbox("내 합주 방", ids, index=default, format_func=lambda rid: labels[rid], key="room_selector")
    st.session_state["active_room_id"] = selected
    return next(r for r in rooms if r["id"] == selected)


def show_active_room(user_id: str):
    room = show_my_rooms(user_id)
    if not room:
        return
    members = get_members(room["id"])
    me = next((m for m in members if m["user_id"] == user_id), None)
    if not me:
        st.error("이 방의 멤버 정보를 찾지 못했습니다.")
        return
    windows = get_windows(room)
    start = date.fromisoformat(str(room["start_date"]))
    end = date.fromisoformat(str(room["end_date"]))
    title, actions = st.columns([4, 1])
    title.subheader(room["room_name"])
    title.caption(f"방 코드 **{room['room_code']}** · 내 이름 **{me['name']}** · {start:%Y.%m.%d} – {end:%Y.%m.%d} · 멤버 {len(members)}명")
    if actions.button("방 나가기", use_container_width=True):
        try:
            SUPABASE.table("room_members").delete().eq("room_id", room["id"]).eq("user_id", user_id).execute()
            st.session_state.pop("active_room_id", None)
            st.rerun()
        except Exception as exc:
            st.error(f"방에서 나가지 못했습니다: {exc}")
    st.info(f"방 코드 **{room['room_code']}**를 공유하세요.")
    selected_date = st.date_input("확인할 날짜", value=max(start, min(date.today(), end)), min_value=start, max_value=end, key=f"room_date_{room['id']}")
    is_host = room["host_id"] == user_id
    tabs = st.tabs(["내 일정 입력", "전체 가능도", "멤버별 일정"] + (["방장 설정"] if is_host else []))
    with tabs[0]:
        show_schedule_input(room, user_id, selected_date, windows)
    with tabs[1]:
        show_overview(room, members, selected_date, windows)
    with tabs[2]:
        show_member_schedule(room, members, selected_date, windows)
    if is_host:
        with tabs[3]:
            show_host_settings(room, windows)


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    require_login()
    global SUPABASE
    SUPABASE = get_supabase()
    user_id = current_user_id()

    top1, top2 = st.columns([5, 1])
    top1.title(APP_TITLE)
    top1.caption(f"Google 계정: {st.user.email}")
    if top2.button("로그아웃", use_container_width=True):
        SUPABASE.auth.sign_out()
        st.logout()

    create_tab, join_tab = st.tabs(["방 만들기", "방 참여"])
    with create_tab:
        show_room_creation(user_id)
    with join_tab:
        show_join_room()
    st.divider()
    show_active_room(user_id)
    st.caption("일정과 방 정보는 Supabase에 저장됩니다. 새로고침해도 Google 로그인과 참여 방을 다시 찾을 수 있습니다.")


SUPABASE: Client

if __name__ == "__main__":
    main()

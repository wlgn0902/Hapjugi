from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from supabase import Client, create_client

APP_TITLE = "합주기가 됩시다 합"
APP_URL = "https://lets-be-hapjugi.streamlit.app/"
SCHEDULE_COMPONENT = components.declare_component("schedule_grid", path="schedule_grid_component")

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


def get_windows(room: dict[str, Any]) -> list[dict[str, Any]]:
    value = room.get("unavailable_windows") or []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [w for w in value if isinstance(w, dict) and "start" in w and "end" in w]


def window_applies(window: dict[str, Any], selected_date: date) -> bool:
    scope = window.get("scope", "all")
    if scope == "all":
        return True
    if scope == "weekdays":
        return selected_date.weekday() < 5
    if scope == "weekends":
        return selected_date.weekday() >= 5
    return selected_date.isoformat() in (window.get("dates") or [])


def is_unavailable(value: str, windows: list[dict[str, Any]], selected_date: date | None = None) -> bool:
    minute = time_to_minute(value)
    for window in windows:
        if selected_date is not None and not window_applies(window, selected_date):
            continue
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


def visible_minutes(windows: list[dict[str, Any]], selected_date: date | None = None) -> list[int]:
    return list(range(0, 1440, 15))


def all_room_dates(room: dict[str, Any]) -> list[date]:
    room_start = date.fromisoformat(str(room["start_date"]))
    room_end = date.fromisoformat(str(room["end_date"]))
    return [room_start + timedelta(days=i) for i in range((room_end-room_start).days + 1)]


def effective_windows_for_date(windows: list[dict[str, Any]], selected_date: date) -> list[dict[str, Any]]:
    return [w for w in windows if window_applies(w, selected_date)]


def compact_visible_minutes_for_date(windows: list[dict[str, Any]], selected_date: date) -> list[int]:
    slots = list(range(0, 1440, 15))
    blocked = {m for m in slots if is_unavailable(minute_to_time(m), windows, selected_date)}
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
    windows: list[dict[str, Any]],
    status: str,
    existing: set[tuple[str, str]],
) -> None:
    rows = []
    for selected_date in dates:
        for minute in minutes:
            slot = minute_to_time(minute)
            if is_unavailable(slot, windows, selected_date):
                continue
            key = (selected_date.isoformat(), slot)
            if key in existing:
                continue
            rows.append({
                "room_id": room_id,
                "user_id": user_id,
                "date": selected_date.isoformat(),
                "time": slot,
                "status": status,
            })
    if rows:
        SUPABASE.table("availability").upsert(rows, on_conflict="room_id,user_id,date,time").execute()

def create_room(room_name: str, display_name: str, password: str, start: date, end: date, windows: list[dict[str, Any]]) -> dict[str, Any]:
    code = make_room_code()
    password_hash_value = None
    if password:
        import bcrypt
        password_hash_value = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    result = SUPABASE.rpc("create_room", {
        "p_room_code": code,
        "p_room_name": room_name,
        "p_host_name": display_name,
        "p_start_date": start.isoformat(),
        "p_end_date": end.isoformat(),
        "p_password_hash": password_hash_value,
    }).execute()
    room_id = result.data[0] if isinstance(result.data, list) else result.data
    if not room_id:
        raise RuntimeError("방 생성에 실패했습니다.")
    SUPABASE.table("rooms").update({"unavailable_windows": windows}).eq("id", room_id).execute()
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
    result = SUPABASE.rpc("join_room", {
        "p_room_code": code,
        "p_name": display_name,
        "p_password": password or None,
    }).execute()
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
    items += '<span class="legend-item"><i class="blocked-swatch"></i>합주 제외</span>'
    st.markdown(f'<div class="legend">{items}</div>', unsafe_allow_html=True)

def render_readonly_grid(dates, minutes, windows, statuses, titles=None) -> None:
    weekday = "월화수목금토일"
    titles = titles or {}
    headers = "".join(f"<th>{d:%m/%d}<br>{weekday[d.weekday()]}</th>" for d in dates)
    rows = []
    for minute in minutes:
        cells = [f'<th class="time">{format_hour_label(minute)}</th>']
        slot = minute_to_time(minute)
        for d in dates:
            key = (d.isoformat(), slot)
            if is_unavailable(slot, windows, d):
                cells.append('<td class="cell blocked" title="합주 제외 시간대"></td>')
            else:
                status = statuses.get(key, "")
                cls = STATUS_CLASSES.get(status, "empty")
                title = titles.get(key, status or "미입력")
                cells.append(f'<td class="cell {cls}" title="{title}"></td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    st.markdown("""
    <style>
    .grid-wrap{overflow:auto;width:100%;border:1px solid #d1d5db;border-radius:10px}.grid{border-collapse:separate;border-spacing:0;width:100%;min-width:520px;table-layout:fixed}
    .grid th,.grid td{border-right:1px solid #d1d5db;border-bottom:1px solid #d1d5db;padding:0;text-align:center}.grid tr>*:last-child{border-right:0}.grid tbody tr:last-child>*{border-bottom:0}
    .grid thead th{height:38px;background:#f8fafc;position:sticky;top:0;z-index:2}.grid .time{width:78px;min-width:78px;text-align:right;padding-right:7px;background:#f8fafc;color:#374151;font-size:.72rem}
    .grid .cell{height:16px}.grid .empty{background:#fff}.grid .blocked{background:#374151}.grid .fully-available{background:#16a34a}.grid .maybe-available{background:#facc15}.grid .uncomfortable{background:#f97316}.grid .unavailable{background:#ef4444}
    .legend{display:flex;flex-wrap:wrap;gap:7px 14px;margin:4px 0 10px;font-size:.82rem}.legend-item{display:inline-flex;align-items:center;gap:5px}.legend-item i{display:inline-block;width:13px;height:13px;border:1px solid #6b7280;border-radius:3px}.blocked-swatch{background:#374151}
    @media(max-width:700px){.grid{min-width:480px}.grid .cell{height:15px}.grid .time{width:64px;min-width:64px;font-size:.65rem}.grid thead th{height:34px;font-size:.75rem}}
    </style>
    """ + f'<div class="grid-wrap"><table class="grid"><thead><tr><th class="time">시간</th>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>', unsafe_allow_html=True)

def render_schedule_component(room, user_id, dates, minutes, windows, statuses, selected_status, editable=True, key="schedule"):
    payload_statuses = {f"{d.isoformat()}|{minute_to_time(m)}": statuses.get((d.isoformat(), minute_to_time(m)), "") for d in dates for m in minutes}
    blocked = {f"{d.isoformat()}|{minute_to_time(m)}" for d in dates for m in minutes if is_unavailable(minute_to_time(m), windows, d)}
    hidden = set()
    for d in dates:
        visible = compact_visible_minutes_for_date(windows, d)
        if visible:
            lo, hi = min(visible), max(visible)
            for m in minutes:
                if m < lo or m > hi:
                    hidden.add(f"{d.isoformat()}|{minute_to_time(m)}")
        else:
            hidden.update(f"{d.isoformat()}|{minute_to_time(m)}" for m in minutes)
    result = SCHEDULE_COMPONENT(
        dates=[d.isoformat() for d in dates],
        minutes=minutes,
        statuses=payload_statuses,
        blocked=list(blocked),
        hidden=list(hidden),
        status_options=STATUS_OPTIONS,
        selected_status=selected_status,
        editable=editable,
        key=key,
        default=None,
    )
    if editable and result and result.get("action") == "paint":
        cells = result.get("cells") or []
        status = result.get("status") or selected_status
        for cell in cells:
            d = date.fromisoformat(cell["date"])
            m = int(cell["minute"])
            if is_unavailable(minute_to_time(m), windows, d):
                continue
            if status == CLEAR_STATUS:
                clear_slot(room["id"], user_id, d, m)
            else:
                upsert_slot(room["id"], user_id, d, m, status)
        st.rerun()


def _window_editor(prefix: str, room_start: date, room_end: date, windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if "create_window_count" not in st.session_state:
        st.session_state["create_window_count"] = max(1, len(windows))
    count = st.session_state["create_window_count"]
    dates = [room_start + timedelta(days=i) for i in range((room_end-room_start).days + 1)]
    st.markdown("**합주 제외 시간대 설정**")
    enabled = st.checkbox("합주 제외 시간대 설정", value=bool(windows) or count > 0, key=f"{prefix}_enabled")
    if not enabled:
        return []
    if count == 0:
        count = 1
        st.session_state["create_window_count"] = 1
        st.rerun()
    for i in range(count):
        old = windows[i] if i < len(windows) else {"start":"00:00","end":"06:00","scope":"all","dates":[]}
        with st.container(border=True):
            h1,h2 = st.columns([5,1])
            h1.markdown(f"**합주 제외 시간대 {i+1}**")
            if h2.button("삭제", key=f"{prefix}_del_{i}"):
                st.session_state[f"{prefix}_delete"] = i
                st.rerun()
            a,b = st.columns(2)
            options=time_choices(); end_options=time_choices(True)
            s=a.selectbox("시작", options, index=options.index(old.get("start","00:00")), key=f"{prefix}_s_{i}")
            e=b.selectbox("종료", end_options, index=end_options.index(old.get("end","06:00")), key=f"{prefix}_e_{i}")
            scope_map={"all":"전체","weekdays":"주중","weekends":"주말","dates":"날짜 선택"}
            scopes=list(scope_map)
            scope=st.radio("적용 날짜", scopes, index=scopes.index(old.get("scope","all")), format_func=lambda x:scope_map[x], horizontal=True, key=f"{prefix}_scope_{i}")
            chosen=[]
            if scope=="dates":
                chosen=st.multiselect("날짜", dates, default=[date.fromisoformat(x) for x in old.get("dates",[]) if x in {d.isoformat() for d in dates}], format_func=lambda d:f"{d:%m/%d} ({'월화수목금토일'[d.weekday()]})", key=f"{prefix}_dates_{i}")
            st.session_state[f"{prefix}_values_{i}"]={"start":s,"end":e,"scope":scope,"dates":[d.isoformat() for d in chosen]}
    if st.button("+", key=f"{prefix}_add", use_container_width=True):
        st.session_state["create_window_count" if prefix=="create" else f"{prefix}_count"] = count+1
        st.rerun()
    return [st.session_state.get(f"{prefix}_values_{i}", {}) for i in range(count)]


def _normalize_window_editor(prefix: str, count: int) -> None:
    delete = st.session_state.pop(f"{prefix}_delete", None)
    if delete is None:
        return
    for i in range(delete, count-1):
        for suffix in ("s","e","scope","dates","values"):
            old=f"{prefix}_{suffix}_{i+1}"; new=f"{prefix}_{suffix}_{i}"
            if old in st.session_state:
                st.session_state[new]=st.session_state[old]
    st.session_state["create_window_count" if prefix=="create" else f"{prefix}_count"]=max(0,count-1)
    st.rerun()


def show_room_creation(user_id: str):
    st.subheader("새 합주 방 만들기")
    if "create_window_count" not in st.session_state:
        st.session_state["create_window_count"] = 0
    room_name = st.text_input("방 이름", placeholder="예: 토요일 밴드 합주", key="create_room_name")
    host_name = st.text_input("내 이름", value=current_user_name(), key="create_host_name")
    password = st.text_input("방 비밀번호 (선택)", type="password", help="비워 두면 비밀번호 없이 방 코드만으로 참여할 수 있습니다.", key="create_password")
    c1,c2=st.columns(2)
    start=c1.date_input("합주 시작일", date.today(), key="create_start")
    end=c2.date_input("합주 종료일", date.today()+timedelta(days=13), key="create_end")
    if end < start:
        st.error("종료일은 시작일보다 빠를 수 없습니다.")
        return
    _normalize_window_editor("create", st.session_state.get("create_window_count",0))
    windows=_window_editor("create", start, end, [])
    if st.button("방 만들기", type="primary", use_container_width=True, key="create_room_submit"):
        room_name,host_name=room_name.strip(),host_name.strip()
        if not room_name or not host_name:
            st.error("방 이름과 내 이름을 입력해 주세요."); return
        valid=[]
        for w in windows:
            if not w: continue
            if w["start"]==w["end"]: st.error("합주 제외 시간대의 시작과 종료를 다르게 설정해 주세요."); return
            if w["scope"]=="dates" and not w["dates"]: st.error("날짜 선택을 사용한 시간대에는 최소 한 날짜를 골라 주세요."); return
            valid.append(w)
        try:
            created=create_room(room_name,host_name,password.strip(),start,end,valid)
            st.session_state["active_room_id"]=created["id"]
            st.session_state["main_section"]="내 합주실"
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
        st.session_state["main_section"] = "내 합주실"
        st.success(f"'{room['room_name']}' 방에 참여했습니다.")
        st.rerun()
    except Exception:
        st.error("방 코드 또는 비밀번호가 맞지 않습니다.")


def show_schedule_input(room, user_id, windows):
    st.subheader("내 일정 입력")
    dates = all_room_dates(room)
    minutes = visible_minutes(windows)
    selected_status = st.radio("입력할 상태", [*STATUS_OPTIONS, CLEAR_STATUS], horizontal=True, key=f"paint_status_{room['id']}")
    rows = get_availability(room["id"], dates)
    statuses = {(str(r["date"]), str(r["time"])[:5]): r["status"] for r in rows if r["user_id"] == user_id}
    b1,b2,b3=st.columns(3)
    if b1.button("합주 완전 가능", use_container_width=True, key=f"bulk_yes_{room['id']}"):
        mine={(str(r['date']),str(r['time'])[:5]) for r in rows if r['user_id']==user_id}
        bulk_set(room['id'],user_id,dates,minutes,windows,STATUS_OPTIONS[0],mine); st.rerun()
    if b2.button("합주 완전 불가", use_container_width=True, key=f"bulk_no_{room['id']}"):
        mine={(str(r['date']),str(r['time'])[:5]) for r in rows if r['user_id']==user_id}
        bulk_set(room['id'],user_id,dates,minutes,windows,STATUS_OPTIONS[3],mine); st.rerun()
    if b3.button("전체 지우기", use_container_width=True, key=f"bulk_clear_{room['id']}"):
        SUPABASE.table('availability').delete().eq('room_id',room['id']).eq('user_id',user_id).execute(); st.rerun()
    show_status_legend()
    render_schedule_component(room,user_id,dates,minutes,windows,statuses,selected_status,editable=True,key=f"editable_{room['id']}")


def show_overview(room, members, windows):
    st.subheader("합주 가능 시간")
    dates=all_room_dates(room); minutes=visible_minutes(windows)
    rows=get_availability(room['id'],dates)
    lookup={(str(r['date']),str(r['user_id']),str(r['time'])[:5]):r['status'] for r in rows}
    statuses={}; ideal=pending=unavailable=0
    for d in dates:
        dk=d.isoformat()
        for minute in minutes:
            slot=minute_to_time(minute); key=(dk,slot)
            if is_unavailable(slot,windows,d): unavailable+=1; continue
            values=[lookup.get((dk,str(m['user_id']),slot)) for m in members]
            received=[v for v in values if v in STATUS_OPTIONS]; missing=len(members)-len(received)
            if missing: pending+=1
            if received: statuses[key]=max(received,key=STATUS_OPTIONS.index)
            if missing==0 and received and statuses[key]==STATUS_OPTIONS[0]: ideal+=1
    c1,c2,c3=st.columns(3)
    c1.metric('전원 합주 가능',f'{ideal*15//60}시간 {ideal*15%60}분')
    c2.metric('응답 대기',f'{pending}칸')
    c3.metric('합주 제외',f'{unavailable}칸')
    show_status_legend()
    render_schedule_component(room,"",dates,minutes,windows,statuses,"",editable=False,key=f"overview_{room['id']}")


def show_member_schedule(room, members, windows):
    st.subheader("멤버별 일정")
    names=[m['name'] for m in members]
    if not names: return
    name=st.selectbox("일정을 확인할 멤버",names,key=f"member_choice_{room['id']}")
    member=next(m for m in members if m['name']==name)
    dates=all_room_dates(room); minutes=visible_minutes(windows)
    rows=get_availability(room['id'],dates)
    statuses={(str(r['date']),str(r['time'])[:5]):r['status'] for r in rows if r['user_id']==member['user_id']}
    show_status_legend()
    render_schedule_component(room,"",dates,minutes,windows,statuses,"",editable=False,key=f"member_{room['id']}_{member['user_id']}")


def show_host_settings(room, windows):
    st.subheader("방장 설정")
    prefix=f"host_{room['id']}"
    count_key=f"host_window_count_{room['id']}"
    if count_key not in st.session_state: st.session_state[count_key]=len(windows)
    enabled=st.checkbox("합주 제외 시간대 설정",value=bool(windows),key=f"{prefix}_enabled")
    if enabled and st.session_state[count_key] == 0:
        st.session_state[count_key]=1
        st.rerun()
    dates=all_room_dates(room)
    selected=[]
    if enabled:
        for i in range(st.session_state[count_key]):
            old=windows[i] if i<len(windows) else {'start':'00:00','end':'06:00','scope':'all','dates':[]}
            a,b=st.columns(2); opts=time_choices(); eopts=time_choices(True)
            sv=a.selectbox('시작',opts,index=opts.index(old.get('start','00:00')),key=f'{prefix}_s_{i}')
            ev=b.selectbox('종료',eopts,index=eopts.index(old.get('end','06:00')),key=f'{prefix}_e_{i}')
            scopes=['all','weekdays','weekends','dates']; labels={'all':'전체','weekdays':'주중','weekends':'주말','dates':'날짜 선택'}
            scope=st.radio('적용 날짜',scopes,index=scopes.index(old.get('scope','all')),format_func=lambda x:labels[x],horizontal=True,key=f'{prefix}_scope_{i}')
            chosen=st.multiselect('날짜',dates,default=[date.fromisoformat(x) for x in old.get('dates',[]) if x in {d.isoformat() for d in dates}],format_func=lambda d:f'{d:%m/%d} ("월화수목금토일"[d.weekday()])',key=f'{prefix}_dates_{i}') if scope=='dates' else []
            selected.append({'start':sv,'end':ev,'scope':scope,'dates':[d.isoformat() for d in chosen]})
            if st.button('삭제',key=f'{prefix}_del_{i}'):
                st.session_state[count_key]=max(0,st.session_state[count_key]-1)
                st.rerun()
        if st.button('+',key=f'{prefix}_add',use_container_width=False):
            st.session_state[count_key]+=1
            st.rerun()
    if st.button('저장',type='primary',key=f'{prefix}_save',use_container_width=True):
        if any(w['start']==w['end'] for w in selected): st.error('시작과 종료가 같은 시간대가 있습니다.'); return
        if any(w['scope']=='dates' and not w['dates'] for w in selected): st.error('날짜 선택을 사용한 시간대에는 최소 한 날짜를 골라 주세요.'); return
        SUPABASE.table('rooms').update({'unavailable_windows':selected if enabled else []}).eq('id',room['id']).execute(); st.rerun()


def show_my_rooms(user_id: str):
    rooms = db_rooms_for_user(user_id)
    if not rooms:
        st.info("아직 참여한 합주 방이 없습니다. 방을 만들거나 초대 코드로 참여해 주세요.")
        return None
    labels = {
        r["id"]: f"{r['room_name']} · 코드 {r['room_code']} · 내 역할 {r['my_membership'].get('role', 'member')}"
        for r in rooms
    }
    ids = [r["id"] for r in rooms]
    current = st.session_state.get("active_room_id")
    default = ids.index(current) if current in ids else 0
    selected = st.selectbox("내 합주 방", ids, index=default, format_func=lambda rid: labels[rid], key="room_selector")
    st.session_state["active_room_id"] = selected
    return next(r for r in rooms if r["id"] == selected)


def show_active_room(user_id: str):
    room=show_my_rooms(user_id)
    if not room: return
    members=get_members(room['id']); me=next((m for m in members if m['user_id']==user_id),None)
    if not me: st.error('이 방의 멤버 정보를 찾지 못했습니다.'); return
    windows=get_windows(room)
    title,actions=st.columns([5,1]); title.subheader(room['room_name']); title.caption(f"방 코드 **{room['room_code']}** · 내 이름 **{me['name']}**")
    if actions.button('방 나가기',use_container_width=True):
        SUPABASE.table('room_members').delete().eq('room_id',room['id']).eq('user_id',user_id).execute(); st.session_state.pop('active_room_id',None); st.rerun()
    is_host=room['host_id']==user_id
    tabs=st.tabs(['내 일정 입력','합주 가능 시간','멤버별 일정']+(['방장 설정'] if is_host else []))
    with tabs[0]: show_schedule_input(room,user_id,windows)
    with tabs[1]: show_overview(room,members,windows)
    with tabs[2]: show_member_schedule(room,members,windows)
    if is_host:
        with tabs[3]: show_host_settings(room,windows)


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    require_login()
    global SUPABASE
    SUPABASE=get_supabase(); user_id=current_user_id()
    top1,top2=st.columns([5,1]); top1.title(APP_TITLE)
    if top2.button('로그아웃',use_container_width=True):
        SUPABASE.auth.sign_out(); st.logout()

    if 'main_section' not in st.session_state:
        st.session_state['main_section']='내 합주실'
    section=st.radio('메뉴',['내 합주실','방 만들기','방 참여하기'],horizontal=True,key='main_section',label_visibility='collapsed')
    st.markdown('''<style>div[role="radiogroup"]{gap:0!important;border-bottom:1px solid #d1d5db;margin-bottom:1rem}div[role="radiogroup"] label{padding:10px 18px!important;border-radius:0!important}div[role="radiogroup"] label:has(input:checked){border-bottom:2px solid #111827;font-weight:700}</style>''',unsafe_allow_html=True)
    if section=='내 합주실':
        show_active_room(user_id)
    elif section=='방 만들기':
        show_room_creation(user_id)
    else:
        show_join_room()


SUPABASE: Client

if __name__ == "__main__":
    main()

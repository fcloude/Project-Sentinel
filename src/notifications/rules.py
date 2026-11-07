import re

from src.events import event_types

# rule trigger name -> the engine event it listens to
TRIGGERS = {
    "unknown_person": event_types.UNKNOWN_PERSON,
    "known_person": event_types.FACE_RECOGNIZED,
    "person": event_types.PERSON_DETECTED,
    "motion": event_types.MOTION_DETECTED,
}
EVENT_TO_TRIGGER = {event: name for name, event in TRIGGERS.items()}

TRIGGER_LABELS = {
    "unknown_person": "An unknown person is seen",
    "known_person": "A known person is recognised",
    "person": "Any person is seen",
    "motion": "Motion is detected",
}

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def valid_time(text) -> bool:
    return bool(TIME_RE.match(text or ""))


def in_window(start, end, now) -> bool:
    """Is `now` (a datetime.time) inside the active hours? Handles windows past midnight.

    No start/end means always active.
    """
    if not start or not end or start == end:
        return True

    current = now.strftime("%H:%M")
    if start < end:
        return start <= current < end
    return current >= start or current < end  # e.g. 22:00 -> 06:00


def validate_rule(form, camera_ids, channel_ids):
    """Form values -> (rule dict, None) or (None, friendly error).

    camera_ids / channel_ids are the ids that really exist.
    """
    name = (form.get("name") or "").strip()
    if not 1 <= len(name) <= 60:
        return None, "Give the rule a name (1-60 characters)."

    trigger = form.get("trigger") or ""
    if trigger not in TRIGGERS:
        return None, "Choose when the rule should fire."

    camera_text = (form.get("camera_id") or "").strip()
    camera_id = None
    if camera_text:
        if not camera_text.isdigit() or int(camera_text) not in camera_ids:
            return None, "That camera doesn't exist."
        camera_id = int(camera_text)

    chosen = []
    for value in form.getlist("channel_ids") if hasattr(form, "getlist") else form.get("channel_ids", []):
        if not str(value).isdigit() or int(value) not in channel_ids:
            return None, "One of the chosen channels doesn't exist."
        chosen.append(int(value))
    if not chosen:
        return None, "Choose at least one place to send the alert."

    start, end = (form.get("start_time") or "").strip(), (form.get("end_time") or "").strip()
    if bool(start) != bool(end):
        return None, "Set both the start and end time for active hours, or leave both empty."
    if start and not (valid_time(start) and valid_time(end)):
        return None, "Times must look like 22:00."

    try:
        cooldown = int((form.get("cooldown_s") or "60").strip())
    except ValueError:
        return None, "Cooldown must be a number of seconds."
    if not 10 <= cooldown <= 86400:
        return None, "Cooldown must be between 10 seconds and 24 hours."

    return {
        "name": name,
        "trigger": trigger,
        "camera_id": camera_id,
        "channel_ids": sorted(set(chosen)),
        "start_time": start or None,
        "end_time": end or None,
        "cooldown_s": cooldown,
        "attach_snapshot": form.get("attach_snapshot") == "on",
    }, None

"""Small presentation helpers; no database or authentication behavior."""
from datetime import datetime

FLASH_MESSAGES = {
    "record_created": ("Record created", "记录已创建"),
    "record_saved": ("Changes saved", "修改已保存"),
    "record_deleted": ("Record deleted", "记录已删除"),
    "type_created": ("Type created", "类型已创建"),
    "type_saved": ("Type saved", "类型已保存"),
    "type_deleted": ("Type deleted", "类型已删除"),
}


def success_redirect(request, url, message):
    from fastapi.responses import RedirectResponse
    if message not in FLASH_MESSAGES:
        raise ValueError("Unknown success message")
    request.session["ui_flash"] = message
    return RedirectResponse(url=url, status_code=303)


def consume_flash(request):
    # Error re-renders use a synthetic GET scope; they must not consume success.
    if request.method != "GET" or request.scope.get("ui_form_error"):
        return None
    key = request.session.pop("ui_flash", None)
    return FLASH_MESSAGES.get(key) if isinstance(key, str) else None


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def display_datetime(value):
    """Minute precision, preserving the stored wall time (no timezone conversion)."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            value = None
    if not isinstance(value, datetime):
        return {"iso": "", "en": "—", "zh": "—"}
    clock = f"{value.hour:02d}:{value.minute:02d}"
    return {
        "iso": value.isoformat(),
        "en": f"{_MONTHS[value.month - 1]} {value.day}, {value.year}, {clock}",
        "zh": f"{value.year}年{value.month}月{value.day}日 {clock}",
    }

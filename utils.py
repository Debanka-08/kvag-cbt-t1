import re


def normalize_student_id(value):
    """'  ab 1234 ' -> 'AB1234'. Removes all whitespace and upper-cases."""
    return re.sub(r"\s+", "", value or "").upper()


def normalize_class(value):
    """Class/section comparison form: no whitespace, upper-case ('xi ' -> 'XI')."""
    return re.sub(r"\s+", "", value or "").upper()


def normalize_name(value):
    """Collapse runs of whitespace and trim, preserving the original capitalisation."""
    return re.sub(r"\s+", " ", (value or "").strip())


def name_key(value):
    """Case-insensitive comparison key for names."""
    return normalize_name(value).casefold()


def axes_username(request, credentials):
    """Normalised username used by django-axes so 'ab1' and ' AB1 ' share one lockout counter."""
    raw = ""
    if credentials:
        raw = credentials.get("username") or ""
    if not raw and request is not None:
        raw = request.POST.get("username", "")
    return re.sub(r"\s+", "", raw).lower()

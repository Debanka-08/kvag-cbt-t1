import csv
import io
import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import StudentRoster, User
from .utils import name_key, normalize_class, normalize_name, normalize_student_id

VERIFY_FAILED = (
    "We could not verify these details against the school's student list. "
    "Please check your Student ID, name, class and section, or contact the school office."
)
ALREADY_REGISTERED = (
    "An account for this Student ID already exists. Please log in, or contact the school office "
    "if you cannot access it."
)


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Student ID / Username",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username", "autocapitalize": "characters"}),
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_student and not user.is_approved:
            raise ValidationError(
                "Your registration is waiting for approval by the school. Please try again later.",
                code="pending_approval",
            )


class StudentRegistrationForm(forms.Form):
    full_name = forms.CharField(label="Full Name", max_length=150)
    student_id = forms.CharField(label="Student ID", max_length=32,
                                 widget=forms.TextInput(attrs={"autocapitalize": "characters"}))
    student_class = forms.CharField(label="Class", max_length=10)
    section = forms.CharField(label="Section", max_length=10)
    password1 = forms.CharField(label="Create Password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm Password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_student_id(self):
        return normalize_student_id(self.cleaned_data["student_id"])

    def clean_full_name(self):
        return normalize_name(self.cleaned_data["full_name"])

    def clean_student_class(self):
        return normalize_class(self.cleaned_data["student_class"])

    def clean_section(self):
        return normalize_class(self.cleaned_data["section"])

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        sid = cleaned.get("student_id")
        if not (sid and cleaned.get("full_name") and cleaned.get("student_class") and cleaned.get("section")):
            return cleaned

        roster = StudentRoster.objects.filter(student_id=sid).first()
        if (
            roster is None
            or not roster.is_active
            or name_key(roster.full_name) != name_key(cleaned["full_name"])
            or roster.student_class != cleaned["student_class"]
            or roster.section != cleaned["section"]
        ):
            raise ValidationError(VERIFY_FAILED)
        if roster.claimed_by_id or User.objects.filter(student_id=sid).exists():
            raise ValidationError(ALREADY_REGISTERED)

        if p1 and p1 == p2:
            candidate = User(username=sid, student_id=sid, full_name=roster.full_name, role=User.Role.STUDENT)
            try:
                validate_password(p1, user=candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    @transaction.atomic
    def save(self):
        """Create the student account. Locks the roster row so concurrent
        registrations for one Student ID cannot both succeed."""
        sid = self.cleaned_data["student_id"]
        roster = StudentRoster.objects.select_for_update().get(student_id=sid)
        if roster.claimed_by_id or not roster.is_active:
            raise ValidationError(ALREADY_REGISTERED)
        user = User(
            username=sid, student_id=sid, role=User.Role.STUDENT,
            full_name=roster.full_name, student_class=roster.student_class, section=roster.section,
            is_approved=not roster.requires_approval,
        )
        user.set_password(self.cleaned_data["password1"])
        user.save()
        roster.claimed_by = user
        roster.save(update_fields=["claimed_by", "updated_at"])
        return user


class RosterImportForm(forms.Form):
    MAX_BYTES = 1024 * 1024
    MAX_ROWS = 5000

    csv_file = forms.FileField(label="CSV file")
    requires_approval = forms.BooleanField(
        required=False, label="Require admin approval after these students register",
    )

    def clean_csv_file(self):
        upload = self.cleaned_data["csv_file"]
        if upload.size > self.MAX_BYTES:
            raise ValidationError("File is too large (limit 1 MB).")
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("The file must be UTF-8 encoded CSV (in Excel: Save As > CSV UTF-8).")

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValidationError("The file is empty.")
        headers = {re.sub(r"[\s_]+", "", (h or "").lower()): h for h in reader.fieldnames}
        required = {"studentid": "Student ID", "name": "Name", "class": "Class", "section": "Section"}
        missing = [label for key, label in required.items() if key not in headers]
        if missing:
            raise ValidationError(
                "Missing column(s): %s. The header row must be exactly: Student ID, Name, Class, Section."
                % ", ".join(missing)
            )

        rows, errors, seen = [], [], set()
        for line_no, raw in enumerate(reader, start=2):
            values = [(raw.get(headers[k]) or "").strip() for k in required]
            if not any(values):
                continue
            sid, name, klass, section = values
            sid = normalize_student_id(sid)
            problems = []
            if not sid:
                problems.append("Student ID is empty")
            elif len(sid) > 32:
                problems.append("Student ID is longer than 32 characters")
            if not name:
                problems.append("Name is empty")
            elif len(name) > 150:
                problems.append("Name is too long")
            if not klass or len(klass) > 10:
                problems.append("Class is empty or too long")
            if not section or len(section) > 10:
                problems.append("Section is empty or too long")
            if sid and sid in seen:
                problems.append(f"Student ID {sid} appears more than once in this file")
            if problems:
                errors.append(f"Line {line_no}: " + "; ".join(problems))
                continue
            seen.add(sid)
            rows.append({"student_id": sid, "full_name": normalize_name(name),
                         "student_class": normalize_class(klass), "section": normalize_class(section)})
            if len(rows) > self.MAX_ROWS:
                raise ValidationError(f"Too many rows (limit {self.MAX_ROWS}). Split the file.")

        if errors:
            shown = errors[:30]
            if len(errors) > 30:
                shown.append(f"...and {len(errors) - 30} more problem(s).")
            raise ValidationError(["No rows were imported. Fix these problems and upload again:"] + shown)
        if not rows:
            raise ValidationError("The file has a header but no student rows.")
        self.rows = rows
        return upload

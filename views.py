from django.contrib import messages
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action

from .decorators import super_admin_required
from .forms import LoginForm, RosterImportForm, StudentRegistrationForm
from .models import StudentRoster, User


class SchoolLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


def register(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    form = StudentRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = form.save()
        except (ValidationError, IntegrityError):
            form.add_error(None, "This Student ID has just been registered. Please log in or contact the school office.")
        else:
            log_action(request, "student.registered", actor=user, target_type="user", target_id=user.pk,
                       student_id=user.student_id)
            if user.is_approved:
                messages.success(request, "Registration complete. You can now log in with your Student ID.")
            else:
                messages.info(request, "Registration received. You can log in once the school approves it.")
            return redirect("accounts:login")
    return render(request, "accounts/register.html", {"form": form})


# ------------------------------------------------------------ roster
@super_admin_required
def roster_list(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    qs = StudentRoster.objects.select_related("claimed_by")
    if q:
        qs = qs.filter(Q(student_id__icontains=q) | Q(full_name__icontains=q))
    if status == "registered":
        qs = qs.filter(claimed_by__isnull=False)
    elif status == "unregistered":
        qs = qs.filter(claimed_by__isnull=True)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "accounts/roster_list.html", {"page": page, "q": q, "status": status})


@super_admin_required
def roster_import(request):
    form = RosterImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        created = updated = skipped = 0
        require_approval = form.cleaned_data["requires_approval"]
        with transaction.atomic():
            for row in form.rows:
                entry = StudentRoster.objects.select_for_update().filter(student_id=row["student_id"]).first()
                if entry is None:
                    StudentRoster.objects.create(requires_approval=require_approval, **row)
                    created += 1
                elif entry.claimed_by_id:
                    skipped += 1  # already registered: never rewrite an active account's details
                else:
                    entry.full_name = row["full_name"]
                    entry.student_class = row["student_class"]
                    entry.section = row["section"]
                    entry.requires_approval = require_approval
                    entry.is_active = True
                    entry.save()
                    updated += 1
        log_action(request, "roster.import", target_type="roster", created=created, updated=updated, skipped=skipped)
        messages.success(request, f"Import finished: {created} added, {updated} updated, "
                                  f"{skipped} skipped (already registered).")
        return redirect("accounts:roster_list")
    return render(request, "accounts/roster_import.html", {"form": form})


# ---------------------------------------------------------- students
@super_admin_required
def student_list(request):
    q = request.GET.get("q", "").strip()
    state = request.GET.get("state", "")
    qs = User.objects.filter(role=User.Role.STUDENT).order_by("student_class", "section", "full_name")
    if q:
        qs = qs.filter(Q(student_id__icontains=q) | Q(full_name__icontains=q))
    if state == "pending":
        qs = qs.filter(is_approved=False)
    elif state == "inactive":
        qs = qs.filter(is_active=False)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "accounts/student_list.html", {"page": page, "q": q, "state": state})


@super_admin_required
@require_POST
def student_action(request, pk):
    student = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    action = request.POST.get("action")
    if action == "approve":
        student.is_approved = True
    elif action == "deactivate":
        student.is_active = False
    elif action == "activate":
        student.is_active = True
    else:
        messages.error(request, "Unknown action.")
        return redirect("accounts:student_list")
    student.save(update_fields=["is_approved", "is_active"])
    log_action(request, f"student.{action}", target_type="user", target_id=student.pk, student_id=student.student_id)
    messages.success(request, f"{student.display_name}: {action} done.")
    return redirect(request.POST.get("next") or "accounts:student_list")


@super_admin_required
def student_password(request, pk):
    student = get_object_or_404(User, pk=pk, role=User.Role.STUDENT)
    form = AdminPasswordChangeForm(student, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request, "student.password_reset", target_type="user", target_id=student.pk,
                   student_id=student.student_id)
        messages.success(request, f"Password reset for {student.display_name}.")
        return redirect("accounts:student_list")
    return render(request, "accounts/student_password.html", {"form": form, "student": student})

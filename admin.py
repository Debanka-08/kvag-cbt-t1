from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import StudentRoster, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "full_name", "role", "student_id", "student_class", "section",
                    "is_approved", "is_active")
    list_filter = ("role", "is_approved", "is_active", "student_class")
    search_fields = ("username", "full_name", "student_id")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("School profile", {"fields": ("role", "full_name", "student_id", "student_class", "section", "is_approved")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("School profile", {"fields": ("role", "full_name", "student_id", "student_class", "section")}),
    )


@admin.register(StudentRoster)
class StudentRosterAdmin(admin.ModelAdmin):
    list_display = ("student_id", "full_name", "student_class", "section", "requires_approval", "is_active", "claimed_by")
    list_filter = ("student_class", "section", "requires_approval", "is_active")
    search_fields = ("student_id", "full_name")

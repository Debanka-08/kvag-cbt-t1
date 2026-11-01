"""Stage 1 tests. Run with:  DJANGO_DEBUG=1 USE_SQLITE_FOR_LOCAL_TESTS=1 python manage.py test
(or against Postgres by setting DATABASE_URL; Django creates a separate test database.)"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog

from .models import StudentRoster, User
from .utils import normalize_student_id

GOOD_PW = "Tr0ub4dor&Maple9"


def make_roster(sid="KV001", name="Asha Verma", klass="11", section="A", **kw):
    return StudentRoster.objects.create(student_id=sid, full_name=name, student_class=klass, section=section, **kw)


def reg_data(**over):
    data = {"full_name": "Asha Verma", "student_id": "KV001", "student_class": "11", "section": "A",
            "password1": GOOD_PW, "password2": GOOD_PW}
    data.update(over)
    return data


class NormalisationTests(TestCase):
    def test_student_id_normalised(self):
        self.assertEqual(normalize_student_id("  kv 001\t"), "KV001")

    def test_roster_and_user_save_normalise(self):
        r = make_roster(sid=" kv 777 ", klass=" xi ", section=" a ")
        self.assertEqual((r.student_id, r.student_class, r.section), ("KV777", "XI", "A"))


class RegistrationTests(TestCase):
    def setUp(self):
        make_roster()

    def test_successful_registration_hashes_password(self):
        resp = self.client.post(reverse("accounts:register"), reg_data(student_id=" kv001 "))
        self.assertRedirects(resp, reverse("accounts:login"))
        u = User.objects.get(student_id="KV001")
        self.assertTrue(u.is_student and u.is_approved)
        self.assertNotEqual(u.password, GOOD_PW)
        self.assertTrue(u.check_password(GOOD_PW))
        self.assertEqual(StudentRoster.objects.get().claimed_by, u)
        self.assertTrue(AuditLog.objects.filter(action="student.registered").exists())

    def test_duplicate_registration_blocked(self):
        self.client.post(reverse("accounts:register"), reg_data())
        resp = self.client.post(reverse("accounts:register"), reg_data(password1=GOOD_PW + "x", password2=GOOD_PW + "x"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(student_id="KV001").count(), 1)

    def test_student_id_not_on_roster_rejected(self):
        resp = self.client.post(reverse("accounts:register"), reg_data(student_id="NOPE1"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(student_id="NOPE1").exists())

    def test_mismatched_details_rejected(self):
        for field, value in [("full_name", "Someone Else"), ("student_class", "12"), ("section", "B")]:
            resp = self.client.post(reverse("accounts:register"), reg_data(**{field: value}))
            self.assertEqual(resp.status_code, 200, field)
        self.assertEqual(User.objects.count(), 0)

    def test_name_match_ignores_case_and_extra_spaces(self):
        self.client.post(reverse("accounts:register"), reg_data(full_name="  asha   VERMA "))
        self.assertTrue(User.objects.filter(student_id="KV001").exists())

    def test_password_mismatch_and_weak_password(self):
        self.client.post(reverse("accounts:register"), reg_data(password2="different"))
        self.client.post(reverse("accounts:register"), reg_data(password1="12345678", password2="12345678"))
        self.assertEqual(User.objects.count(), 0)

    def test_inactive_roster_entry_rejected(self):
        StudentRoster.objects.update(is_active=False)
        self.client.post(reverse("accounts:register"), reg_data())
        self.assertEqual(User.objects.count(), 0)

    def test_approval_required_blocks_login_until_approved(self):
        StudentRoster.objects.update(requires_approval=True)
        self.client.post(reverse("accounts:register"), reg_data())
        u = User.objects.get(student_id="KV001")
        self.assertFalse(u.is_approved)
        resp = self.client.post(reverse("accounts:login"), {"username": "KV001", "password": GOOD_PW})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        u.is_approved = True
        u.save()
        self.client.post(reverse("accounts:login"), {"username": "KV001", "password": GOOD_PW})
        self.assertIn("_auth_user_id", self.client.session)


class LoginAndPermissionTests(TestCase):
    def setUp(self):
        make_roster()
        self.client.post(reverse("accounts:register"), reg_data())
        self.client.logout()
        self.admin = User.objects.create_superuser("principal", "p@example.com", GOOD_PW)
        self.teacher = User.objects.create_user("teacher1", password=GOOD_PW, role=User.Role.TEACHER, full_name="T One")

    def test_student_login_is_case_and_space_insensitive_and_redirects(self):
        resp = self.client.post(reverse("accounts:login"), {"username": " kv001 ", "password": GOOD_PW})
        self.assertRedirects(resp, reverse("core:home"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("core:home")), reverse("core:student_dashboard"))

    def test_wrong_password_fails(self):
        self.client.post(reverse("accounts:login"), {"username": "KV001", "password": "wrong"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.login(username="KV001", password=GOOD_PW)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_superuser_gets_super_admin_role(self):
        self.assertEqual(self.admin.role, User.Role.SUPER_ADMIN)

    def test_student_cannot_open_staff_or_admin_pages(self):
        self.client.login(username="KV001", password=GOOD_PW)
        for name in ["core:staff_dashboard", "accounts:roster_list", "accounts:roster_import", "accounts:student_list"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_teacher_cannot_manage_roster_but_sees_staff_dashboard(self):
        self.client.login(username="teacher1", password=GOOD_PW)
        self.assertEqual(self.client.get(reverse("core:staff_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:roster_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("core:student_dashboard")).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("accounts:roster_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])

    def test_admin_can_reset_password_and_deactivate(self):
        student = User.objects.get(student_id="KV001")
        self.client.login(username="principal", password=GOOD_PW)
        new_pw = "N3w-Strong-Pass-77"
        self.client.post(reverse("accounts:student_password", args=[student.pk]), {"password1": new_pw, "password2": new_pw})
        student.refresh_from_db()
        self.assertTrue(student.check_password(new_pw))
        self.client.post(reverse("accounts:student_action", args=[student.pk]), {"action": "deactivate"})
        student.refresh_from_db()
        self.assertFalse(student.is_active)
        self.assertTrue(AuditLog.objects.filter(action="student.password_reset").exists())

    def test_authenticated_pages_are_not_cacheable(self):
        self.client.login(username="principal", password=GOOD_PW)
        self.assertIn("no-cache", self.client.get(reverse("core:staff_dashboard"))["Cache-Control"])


class RosterImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("principal", "p@example.com", GOOD_PW)
        self.client.login(username="principal", password=GOOD_PW)

    def upload(self, text, **extra):
        f = SimpleUploadedFile("roster.csv", text.encode("utf-8"), content_type="text/csv")
        return self.client.post(reverse("accounts:roster_import"), {"csv_file": f, **extra})

    def test_valid_import(self):
        resp = self.upload("Student ID,Name,Class,Section\nkv 1,Ravi K,11,a\nKV2,Meena S,12,B\n")
        self.assertRedirects(resp, reverse("accounts:roster_list"))
        self.assertEqual(StudentRoster.objects.count(), 2)
        self.assertTrue(StudentRoster.objects.filter(student_id="KV1", section="A").exists())
        self.assertTrue(AuditLog.objects.filter(action="roster.import").exists())

    def test_invalid_file_imports_nothing(self):
        resp = self.upload("Student ID,Name,Class,Section\nKV1,Ravi,11,A\nKV1,Dup,11,A\n,NoId,11,A\n")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StudentRoster.objects.count(), 0)

    def test_missing_header_rejected(self):
        resp = self.upload("ID,Name\nKV1,Ravi\n")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StudentRoster.objects.count(), 0)

    def test_reimport_does_not_change_registered_student(self):
        self.upload("Student ID,Name,Class,Section\nKV1,Ravi K,11,A\n")
        self.client.logout()
        self.client.post(reverse("accounts:register"), reg_data(student_id="KV1", full_name="Ravi K"))
        self.client.login(username="principal", password=GOOD_PW)
        self.upload("Student ID,Name,Class,Section\nKV1,Changed Name,12,Z\n")
        self.assertEqual(StudentRoster.objects.get(student_id="KV1").full_name, "Ravi K")


class HealthCheckTests(TestCase):
    def test_healthz_runs_real_query(self):
        resp = self.client.get(reverse("core:healthz"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["database"], "ok")


class RateLimitTests(TestCase):
    @override_settings(AXES_FAILURE_LIMIT=3)
    def test_repeated_failures_lock_account(self):
        make_roster()
        self.client.post(reverse("accounts:register"), reg_data())
        self.client.logout()
        for _ in range(3):
            self.client.post(reverse("accounts:login"), {"username": "KV001", "password": "bad"})
        resp = self.client.post(reverse("accounts:login"), {"username": "kv001", "password": GOOD_PW})
        self.assertEqual(resp.status_code, 429)

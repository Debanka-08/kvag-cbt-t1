from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.SchoolLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),  # POST only (Django 5)
    path("register/", views.register, name="register"),
    path("roster/", views.roster_list, name="roster_list"),
    path("roster/import/", views.roster_import, name="roster_import"),
    path("students/", views.student_list, name="student_list"),
    path("students/<int:pk>/action/", views.student_action, name="student_action"),
    path("students/<int:pk>/password/", views.student_password, name="student_password"),
]

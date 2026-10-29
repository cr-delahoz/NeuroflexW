from django.urls import path

from .views import (
    ApiHealthCheckView,
    ForcedConnectivityModeView,
    LocalConfigView,
    PasswordResetView,
    PdfPermissionGrantView,
    PdfPermissionRevokeView,
    ProfessionCreateView,
    ProfessionDeleteView,
    ProfessionListView,
    RequestPasswordResetView,
    ResetPasswordConfirmView,
    RoleBasedLoginView,
    RoleBasedLogoutView,
    SpecialistCreateView,
    SpecialistProfileView,
    UserActivateView,
    UserDeactivateView,
    UserDeleteView,
    UserListView,
    UserNameUpdateView,
    UserProfessionUpdateView,
    UserRoleUpdateView,
)

app_name = "accounts"

urlpatterns = [
    path("login/", RoleBasedLoginView.as_view(), name="login"),
    path("logout/", RoleBasedLogoutView.as_view(), name="logout"),
    path("local-config/", LocalConfigView.as_view(), name="local-config"),
    path("force-mode/", ForcedConnectivityModeView.as_view(), name="force-mode"),
    path("api-health/", ApiHealthCheckView.as_view(), name="api-health"),
    path(
        "reset-password/",
        RequestPasswordResetView.as_view(),
        name="reset-password-request",
    ),
    path(
        "reset-password/confirm/",
        ResetPasswordConfirmView.as_view(),
        name="reset-password-confirm",
    ),
    path("users/", UserListView.as_view(), name="user-list"),
    path("users/create/", SpecialistCreateView.as_view(), name="user-create"),
    path("profile/", SpecialistProfileView.as_view(), name="specialist-profile"),
    path("users/<int:user_id>/activate/", UserActivateView.as_view(), name="user-activate"),
    path(
        "users/<int:user_id>/deactivate/",
        UserDeactivateView.as_view(),
        name="user-deactivate",
    ),
    path(
        "users/<int:user_id>/reset-password/",
        PasswordResetView.as_view(),
        name="user-reset-password",
    ),
    path(
        "users/<int:user_id>/delete/",
        UserDeleteView.as_view(),
        name="user-delete",
    ),
    path(
        "users/<int:user_id>/edit-name/",
        UserNameUpdateView.as_view(),
        name="user-edit-name",
    ),
    path(
        "users/<int:user_id>/update-role/",
        UserRoleUpdateView.as_view(),
        name="user-update-role",
    ),
    path(
        "users/<int:user_id>/update-profession/",
        UserProfessionUpdateView.as_view(),
        name="user-update-profession",
    ),
    path(
        "professions/",
        ProfessionListView.as_view(),
        name="profession-list",
    ),
    path(
        "professions/create/",
        ProfessionCreateView.as_view(),
        name="profession-create",
    ),
    path(
        "professions/<str:profession_id>/delete/",
        ProfessionDeleteView.as_view(),
        name="profession-delete",
    ),
    path(
        "users/<int:user_id>/grant-pdf-permission/",
        PdfPermissionGrantView.as_view(),
        name="user-grant-pdf-permission",
    ),
    path(
        "users/<int:user_id>/revoke-pdf-permission/",
        PdfPermissionRevokeView.as_view(),
        name="user-revoke-pdf-permission",
    ),
]

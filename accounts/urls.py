from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path(
        'password_change/',
        views.UserPasswordChangeView.as_view(),
        name='password_change',
    ),
    path(
        'password_change/done/',
        views.UserPasswordChangeDoneView.as_view(),
        name='password_change_done',
    ),
    path(
        'password_reset/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset_form.html',
            email_template_name='accounts/password_reset_email.html',
            subject_template_name='accounts/password_reset_subject.txt',
            success_url=reverse_lazy('accounts:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password_reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/password_reset_done.html'
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/password_reset_complete.html'
        ),
        name='password_reset_complete',
    ),
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/add/', views.UserCreateView.as_view(), name='user_add'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    path(
        'users/<int:pk>/password/',
        views.UserPasswordView.as_view(),
        name='user_password',
    ),
    path(
        'users/<int:pk>/active/',
        views.UserToggleActiveView.as_view(),
        name='user_toggle_active',
    ),
    path(
        'users/<int:pk>/link/',
        views.UserLinkView.as_view(),
        name='user_link',
    ),
]
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db import models
from django.forms import inlineformset_factory

from accounts.models import UserProfile
from core.models import ClassStream, Department, Teacher, TeacherAssignment


def _apply_bootstrap(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select) and not isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-select')
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        else:
            widget.attrs.setdefault('class', 'form-control')


class TeacherAssignmentForm(forms.ModelForm):
    class Meta:
        model = TeacherAssignment
        fields = ['class_stream', 'subject']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


TeacherAssignmentFormSet = inlineformset_factory(
    Teacher,
    TeacherAssignment,
    form=TeacherAssignmentForm,
    extra=1,
    can_delete=True,
)


class TeacherForm(forms.ModelForm):
    class UserAction(models.TextChoices):
        KEEP = 'keep', 'Keep current account'
        CREATE = 'create', 'Create a new user account'
        LINK = 'link', 'Link an existing user account'

    user_action = forms.ChoiceField(
        choices=UserAction.choices,
        widget=forms.RadioSelect,
        required=False,
    )
    username = forms.CharField(max_length=150, required=False, label='Username')
    password1 = forms.CharField(
        widget=forms.PasswordInput(), required=False, label='Password'
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(), required=False, label='Confirm password'
    )
    link_user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='Existing user',
    )
    class_teacher_for = forms.ModelChoiceField(
        queryset=ClassStream.objects.all(),
        required=False,
        label='Class teacher for',
        empty_label='— Not a class teacher —',
    )

    class Meta:
        model = Teacher
        fields = [
            'employee_no', 'first_name', 'middle_name', 'last_name', 'gender',
            'department', 'phone', 'email', 'date_joined', 'is_active', 'classes',
        ]
        widgets = {
            'date_joined': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
        self.fields['user_action'].widget.attrs.update({'class': 'form-check-input'})
        if not self.instance.pk:
            self.fields['user_action'].initial = self.UserAction.CREATE
            self.fields['user_action'].choices = [
                c for c in self.UserAction.choices
                if c[0] != self.UserAction.KEEP
            ]
        else:
            self.fields['user_action'].initial = self.UserAction.KEEP

        qs = User.objects.filter(
            profile__role=UserProfile.Roles.TEACHER,
            is_superuser=False,
            teacher__isnull=True,
        )
        if self.instance.pk and self.instance.user_id:
            qs = qs | User.objects.filter(pk=self.instance.user_id)
        self.fields['link_user'].queryset = qs.distinct()

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean_link_user(self):
        user = self.cleaned_data.get('link_user')
        if not user:
            return user
        if user.is_superuser:
            raise forms.ValidationError('A superuser cannot be linked as a teacher.')
        profile = getattr(user, 'profile', None)
        if profile is None or profile.role != UserProfile.Roles.TEACHER:
            raise forms.ValidationError('Only users with the Teacher role can be linked.')
        other = Teacher.objects.filter(user=user)
        if self.instance.pk:
            other = other.exclude(pk=self.instance.pk)
        if other.exists():
            raise forms.ValidationError('This user is already linked to another teacher.')
        return user

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get('user_action')
        creating = self.instance.pk is None

        if action == self.UserAction.KEEP and creating:
            self.add_error(
                'user_action',
                'New teachers must have a user account created or linked.',
            )
            return cleaned

        if action == self.UserAction.CREATE:
            username = cleaned.get('username', '')
            password1 = cleaned.get('password1', '')
            password2 = cleaned.get('password2', '')
            if not username:
                self.add_error('username', 'A username is required.')
            if not password1:
                self.add_error('password1', 'A password is required.')
            if password1 and password2 and password1 != password2:
                self.add_error('password2', 'Passwords do not match.')
            if password1 and password2 and password1 == password2:
                try:
                    validate_password(password2, user=User(username=username or 'user'))
                except forms.ValidationError as exc:
                    self.add_error('password1', exc.messages)
        elif action == self.UserAction.LINK and not cleaned.get('link_user'):
            self.add_error('link_user', 'Select an existing user to link.')
        elif action is None or action not in self.UserAction.values:
            self.add_error(
                'user_action',
                'Choose how to associate a user account with this teacher.',
            )
        return cleaned

    def save(self, commit=True):
        teacher = super().save(commit=False)
        action = self.cleaned_data.get('user_action', self.UserAction.KEEP)
        user = teacher.user
        if action == self.UserAction.CREATE:
            username = self.cleaned_data['username']
            user = User.objects.create_user(
                username=username,
                password=self.cleaned_data['password2'],
                email=teacher.email or '',
            )
            profile = user.profile
            profile.role = UserProfile.Roles.TEACHER
            profile.save(update_fields=['role'])
        elif action == self.UserAction.LINK:
            user = self.cleaned_data.get('link_user')
        teacher.user = user
        if commit:
            teacher.save()
            self.save_m2m()
            stream = self.cleaned_data.get('class_teacher_for')
            if stream:
                # Claim the chosen stream and release any other streams this
                # teacher currently heads, preserving the single-head invariant.
                if stream.class_teacher_id != teacher.pk:
                    ClassStream.objects.filter(class_teacher=teacher).exclude(
                        pk=stream.pk
                    ).update(class_teacher=None)
                    stream.class_teacher = teacher
                    stream.save(update_fields=['class_teacher'])
            else:
                # Field intentionally shown: a blank dropdown on an edit means
                # the teacher is no longer a class teacher.
                ClassStream.objects.filter(class_teacher=teacher).update(
                    class_teacher=None
                )
        return teacher


class TeacherFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label='Search',
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by name or employee no.',
            'class': 'form-control',
        }),
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        required=False,
        label='Department',
        empty_label='All departments',
    )
    is_active = forms.ChoiceField(
        choices=[
            ('', 'All statuses'),
            ('1', 'Active'),
            ('0', 'Inactive'),
        ],
        required=False,
        label='Status',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
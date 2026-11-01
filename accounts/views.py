from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from audit.models import AuditEvent
from audit.services import record_event
from hostels.models import Bed

from .decorators import roles_required
from .forms import AccountCreationForm, AccountUpdateForm, ProfileSettingsForm
from .models import User


@never_cache
@require_http_methods(['GET', 'POST'])
def sign_in(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        authenticated = authenticate(request, username=username, password=password)
        if authenticated:
            login(request, authenticated)
            return redirect('dashboard')
        else:
            error = 'Invalid username or password'
    return render(request, 'accounts/login.html', {'error': error})


@require_http_methods(['POST'])
@login_required
def sign_out(request):
    logout(request)  # Django flushes the session and invalidates its key.
    return redirect('login')


@roles_required(*User.Role.values)
def dashboard(request):
    role_templates = {
        User.Role.ADMIN: 'accounts/dashboard_admin.html',
        User.Role.WARDEN: 'accounts/dashboard_warden.html',
        User.Role.STUDENT: 'accounts/dashboard_student.html',
    }
    template = role_templates[request.user.role]
    context = {}
    if request.user.role == User.Role.STUDENT:
        context.update({
            'available_bed_count': Bed.objects.filter(
                status=Bed.BedStatus.AVAILABLE,
                room__hostel__is_active=True,
            ).count(),
        })
    return render(request, template, context)


@login_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def settings_view(request):
    profile_form = ProfileSettingsForm(instance=request.user)
    password_form = PasswordChangeForm(user=request.user)

    if request.method == 'POST':
        section = request.POST.get('section')
        if section == 'profile':
            profile_form = ProfileSettingsForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                if profile_form.has_changed():
                    profile_form.save()
                    record_event(user=request.user, action=AuditEvent.Action.UPDATE, record=request.user)
                messages.success(request, 'Your profile settings have been saved.')
                return redirect('settings')
        elif section == 'password':
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                record_event(user=user, action=AuditEvent.Action.UPDATE, record=user)
                messages.success(request, 'Your password has been changed.')
                return redirect('settings')

    return render(request, 'accounts/settings.html', {
        'profile_form': profile_form,
        'password_form': password_form,
    })


admin_role_required = roles_required(User.Role.ADMIN)


@login_required
@admin_role_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def user_management(request):
    if request.method == 'POST':
        form = AccountCreationForm(request.POST)
        if form.is_valid():
            account = form.save()
            record_event(user=request.user, action=AuditEvent.Action.CREATE, record=account)
            return redirect('user-management')
    else:
        form = AccountCreationForm()
    users = User.objects.order_by('username')
    return render(request, 'accounts/user_management.html', {'form': form, 'users': users})


@login_required
@admin_role_required
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def update_user(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        form = AccountUpdateForm(request.POST, instance=target)
        if form.is_valid():
            if form.has_changed():
                form.save()
                record_event(user=request.user, action=AuditEvent.Action.UPDATE, record=target)
            return redirect('user-management')
    else:
        form = AccountUpdateForm(instance=target)
    return render(request, 'accounts/user_update.html', {'form': form, 'account': target})


@login_required
@admin_role_required
@require_http_methods(['POST'])
@transaction.atomic
def deactivate_user(request, user_id):
    target = get_object_or_404(User.objects.select_for_update(), pk=user_id)
    if target.pk == request.user.pk:
        return HttpResponseForbidden('You cannot deactivate your own account')
    if target.is_active:
        target.is_active = False
        target.save(update_fields=['is_active'])
        record_event(user=request.user, action=AuditEvent.Action.DEACTIVATE, record=target)
    return redirect('user-management')

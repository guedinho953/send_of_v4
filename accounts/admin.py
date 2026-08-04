from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, Tenant, ServerProfile


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'cnpj', 'role', 'is_active', 'created_at']
    list_filter = ['role', 'is_active']
    search_fields = ['name', 'cnpj']


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'first_name', 'last_name', 'role', 'tenant', 'is_active']
    list_filter = ['role', 'is_active', 'is_staff']
    search_fields = ['email', 'first_name', 'last_name']
    ordering = ['email']

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Informações Pessoais', {'fields': ('first_name', 'last_name', 'role')}),
        ('Projudi', {'fields': ('projudi_password',), 'description': 'Senha da assinatura eletrônica do Projudi — usada automaticamente pelo fluxo de certidões quando a assinatura não está salva no Projudi.'}),
        ('Organização', {'fields': ('tenant', 'vara', 'comarca')}),
        ('Permissões', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Datas importantes', {'fields': ('last_login',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'password1', 'password2', 'role', 'tenant', 'projudi_password'),
        }),
    )


@admin.register(ServerProfile)
class ServerProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'oab', 'specialization']
    search_fields = ['user__email', 'oab']

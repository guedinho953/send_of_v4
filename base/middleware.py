from django.conf import settings
from django.http import HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin


class TenantMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if not request.user.is_authenticated:
            return None

        tenant_id = request.session.get('tenant_id')
        if tenant_id:
            request.tenant_id = tenant_id
        elif hasattr(request.user, 'tenant_id'):
            request.tenant_id = request.user.tenant_id
        else:
            request.tenant_id = None

        return None


class FilePermissionMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        return response

    def can_access_file(self, user, file_obj):
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if hasattr(file_obj, 'user'):
            return file_obj.user_id == user.id
        if hasattr(file_obj, 'tenant_id'):
            return file_obj.tenant_id == getattr(user, 'tenant_id', None)
        return True

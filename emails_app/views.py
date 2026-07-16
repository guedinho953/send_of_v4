from django.views.generic import TemplateView

class EmailListView(TemplateView):
    template_name = 'emails_app/email_list.html'

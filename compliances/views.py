from django.views.generic import TemplateView

class ComplianceListView(TemplateView):
    template_name = 'compliances/compliance_list.html'

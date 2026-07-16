from django.views.generic import TemplateView

class DocumentListView(TemplateView):
    template_name = 'documents/document_list.html'

from django.views.generic import TemplateView

class VectorListView(TemplateView):
    template_name = 'vector_store/vector_list.html'

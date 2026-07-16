from django.views.generic import TemplateView

class CommandListView(TemplateView):
    template_name = 'commands/command_list.html'

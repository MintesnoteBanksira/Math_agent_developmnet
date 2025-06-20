from django.urls import path
from . import views

app_name = 'math_agent'

urlpatterns = [
    path('', views.BatchListView.as_view(), name='batch_list'),
    path('generate/', views.GenerateView.as_view(), name='generate'),
    path('batch/<int:pk>/', views.BatchDetailView.as_view(), name='batch_detail'),
    path('batch/<int:batch_id>/problems/', views.ProblemListView.as_view(), name='problems'),
    path('problem/<int:pk>/', views.ProblemDetailView.as_view(), name='problem_detail'),
    path('problems/', views.AllProblemsView.as_view(), name='all_problems'),
    path('export/problems/', views.export_problems_csv, name='export_problems'),
] 
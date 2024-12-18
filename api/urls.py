# urls.py
from django.urls import path
from .views import UploadData, ProcessQuery, GetChartRecommendations
print("Registering URL patterns")

urlpatterns = [
    path('upload/', UploadData.as_view(), name='upload-data'),
    path('process-query/', ProcessQuery.as_view(), name='process-query'),
    path('Visualize/', GetChartRecommendations.as_view(), name='get-chart-recommendations'),
]

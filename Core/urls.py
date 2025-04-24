from .views import *
from django.urls import path

urlpatterns = [
    path('',analyze,name='Analyze'),
    path('analyze',getData,name='getdata'),    
]
from django.urls import path
from pdf_signer import views

app_name = 'pdf_signer'

urlpatterns = [
    path('', views.upload_pdf, name='upload'),
    path('preview/<int:pk>/', views.preview_pdf, name='preview'),
    path('sign/<int:pk>/', views.sign_pdf, name='sign'),
    path('download/<int:pk>/', views.download_pdf, name='download'),
] 
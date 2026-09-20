from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view),
    path('home/', views.home_view, name='home'),
    path('jobs/', views.job_list, name='job_list'),
    path('categories/', views.category_list_view, name='category_list'),
    path('blog/', views.blog_list_view, name='blog_list'),
    path('blog/<slug:slug>/', views.blog_detail_view, name='blog_detail'),
    path('job/<int:pk>/', views.job_detail, name='job_detail'),
    path('advertisement/<int:pk>/impression.gif', views.advertisement_impression, name='advertisement_impression'),
    path('advertisement/<int:pk>/click/', views.advertisement_click, name='advertisement_click'),
    path('privacy-policy/', views.legal_page, {'page_type': 'privacy'}, name='privacy_policy'),
    path('about-us/', views.legal_page, {'page_type': 'about'}, name='about_us'),
    path('contact-us/', views.legal_page, {'page_type': 'contact'}, name='contact_us'),
    path('contact-us/message/', views.contact_message, name='contact_message'),
    path('terms-and-conditions/', views.legal_page, {'page_type': 'terms'}, name='terms_and_conditions'),
    path('pages/<slug:slug>/', views.custom_page, name='custom_page'),
]
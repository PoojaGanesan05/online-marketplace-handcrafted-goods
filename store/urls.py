from django.urls import path
from . import views

urlpatterns = [
    # Home & Authentication
    path('', views.home, name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Role selection
    path('select-role/', views.role_selection, name='role_selection'),

    # Seller dashboard and order confirmation
    path('seller/dashboard/', views.seller_dashboard, name='seller_dashboard'),
    path('confirm-order/<int:order_id>/', views.confirm_order, name='confirm_order'),

    # Buyer dashboard
    path('buyer/dashboard/', views.buyer_dashboard, name='buyer_dashboard'),

    # Product actions (Buyer)
    path('order/<int:product_id>/', views.place_order, name='place_order'),
    path('wishlist/add/<int:product_id>/', views.add_to_wishlist, name='add_to_wishlist'),
    path('wishlist/remove/<int:product_id>/', views.remove_from_wishlist, name='remove_from_wishlist'),
    path('wishlist/', views.view_wishlist, name='view_wishlist'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:product_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/', views.view_cart, name='view_cart'),

    # Reviews
    path('review/<int:product_id>/', views.submit_review, name='submit_review'),
    path('reviews/<int:product_id>/', views.view_reviews, name='view_reviews'),

    # Notifications
    path('notifications/', views.view_notifications, name='view_notifications'),

    # Payment Flow
    path('review-order/<int:product_id>/', views.review_order, name='review_order'),
    path('payment/', views.payment_selection, name='payment_selection'),
    path('confirm-order/', views.confirm_order_page, name='confirm_order_page'),
    path('orders/', views.order_history, name='order_history'),

    # Seller product / order management
    path('product/edit/<int:product_id>/', views.edit_product, name='edit_product'),
    path('product/delete/<int:product_id>/', views.delete_product, name='delete_product'),
    path('reject-order/<int:order_id>/', views.reject_order, name='reject_order'),
]

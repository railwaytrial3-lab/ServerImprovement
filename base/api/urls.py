from django.urls import path
from . import views
from rest_framework_simplejwt.views import TokenObtainPairView

urlpatterns = [
    path('auth/me/',views.me),

    # Auth
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', views.CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/signup/',views.register),
    path('auth/logout/',views.logout),
    path('auth/google/', views.google_login, name='google_login'),

    # # Product
    path('products/',views.get_all_products),
    path('products/best-sellers/', views.get_best_sellers, name='best-sellers'),
    path('products/top-selling-overall/', views.get_top_selling_product_overall, name='top-selling-overall'),
    path('products/<str:pk>/',views.get_product_detail),
    
    # # Cart
    path('cart/', views.get_cart, name='get_cart'),
    path('cart/add/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:item_id>/', views.update_cart_item, name='update_cart_item'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/clear/', views.clear_cart, name='clear_cart'),
    path('cart/merge/', views.merge_cart, name='merge-cart'),

    # # Order
    path('orders/place/', views.place_order, name='place_order'),
    path('orders/history/', views.get_my_orders, name='my_orders'),
    

    # # Wishlist
    path('wishlist/', views.get_wishlist, name='get_wishlist'),
    path('wishlist/toggle/', views.toggle_wishlist, name='toggle_wishlist'),

    path('reviews/add/', views.add_review, name='add_review'),
    path('products/<str:product_id>/reviews/', views.get_product_reviews, name='product_reviews'),

    ################################################## (Paymob)
    path('payment/paymob/create-checkout/', views.paymob_checkout, name='paymob-create-checkout'),
    path('payment/webhook/paymob/', views.paymob_webhook, name='paymob-webhook'),


    ## Dashboard
    path('dashboard/orders/recent/',views.get_latest_orders),
    path('dashboard/stats/',views.get_dashboard_stats),
    path('dashboard/analytics/', views.AdminDashboardAnalyticsView.as_view(), name='admin-dashboard-analytics'),
    path('dashboard/notifications/', views.get_admin_notifications, name='admin-notifications'),
    path('dashboard/notifications/mark-read/', views.mark_notifications_read, name='admin-notifications-read-all'),
    path('dashboard/notifications/<int:pk>/mark-read/', views.mark_notifications_read, name='admin-notifications-read-single'),
    path('dashboard/reviews/',views.get_all_reviews),
    path('dashboard/order/<str:pk>/',views.order_detail_action),
    path('dashboard/make-admin/',views.promote_user_to_admin),
    path('dashboard/categories/', views.manage_categories, name='manage-categories'),
    path('dashboard/categories/<int:pk>/', views.manage_category_detail, name='manage-category-detail'),

    # Shipping / Governorates
    path('shipping/governorates/', views.get_governorates, name='get-governorates'),
    path('dashboard/governorates/', views.manage_governorates, name='manage-governorates'),
    path('dashboard/governorates/<int:pk>/', views.manage_governorate_detail, name='manage-governorate-detail'),

    ###########

    path('dashboard/products/create/', views.create_product_api, name='dash-create-product'),
    # 2. Add Variants (Dynamic URL needs product_id)
    path('dashboard/products/<int:product_id>/variants/add/', views.add_variants_to_product_api, name='dash-add-variants'),
    # 3. Upload Image (Dynamic URL needs variant_id)
    path('dashboard/variants/<int:variant_id>/upload-image/', views.upload_variant_image_api, name='dash-upload-image'),
    path('dashboard/images/<int:image_id>/delete/', views.delete_variant_image_api, name='dash-delete-image'),
    path('dashboard/images/<int:image_id>/set-thumbnail/', views.set_variant_thumbnail_api, name='dash-set-thumbnail'),
    # 4. Update Variant
    # Edit / Deactivate Product
    path('dashboard/products/<int:pk>/manage/', views.dashboard_product_detail_api, name='dash-manage-product'),
    # Edit / Deactivate Variant
    path('dashboard/variants/<int:variant_id>/manage/', views.dashboard_variant_detail_api, name='dash-manage-variant'),


    # # Charts
    path('charts/products/low/',views.get_low_chart_info),
    path('charts/products/top-selling/',views.get_top_sales_chart_info),
    path('charts/sales-orders/',views.get_sales_orders_chart),
    
    # # Banners
    path('banners/', views.get_active_banners, name='active-banners'),
    path('dashboard/banners/', views.manage_banners, name='manage-banners'),
    path('dashboard/banners/<int:pk>/', views.manage_banner_detail, name='manage-banner-detail'),

    # # Site Settings
    path('settings/', views.get_site_settings, name='get-site-settings'),
    path('dashboard/settings/', views.manage_site_settings, name='manage-site-settings'),
]
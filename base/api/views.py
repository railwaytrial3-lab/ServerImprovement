# pyrefly: ignore [missing-import]
from django.utils.translation import gettext as _
from rest_framework.decorators import api_view,permission_classes, parser_classes
import json
from base.utils import send_telegram_notification
# pyrefly: ignore [missing-import]
from django.http import HttpResponse
import stripe
# pyrefly: ignore [missing-import]
from rest_framework.response import Response
# pyrefly: ignore [missing-import]
from django.db import transaction
import requests
import time
from datetime import timedelta
import datetime
from django.utils import timezone
from django.db.models.functions import TruncMonth
from django.db.models import Count,F,Avg,Sum,Prefetch,Q,Min,Max, DecimalField, Value, OuterRef, Subquery
from rest_framework import status
from .permissions import UnAuthenticated
from django.db.models.functions import Coalesce
from rest_framework.permissions import IsAdminUser,IsAuthenticated,AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from base import models
from django.db import IntegrityError
from . import serializers
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_page
from decimal import Decimal
from rest_framework.pagination import PageNumberPagination
from django.db import connection
from django.contrib.auth import get_user_model # <--- 1. Use this
from django.conf import settings
from django.http import JsonResponse
from rest_framework.parsers import MultiPartParser, FormParser

from rest_framework_simplejwt.views import TokenRefreshView

class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = serializers.CustomTokenRefreshSerializer

################################# Auth
@api_view(['POST'])
@permission_classes([UnAuthenticated])
def register(request):
    email = request.data.get('email', '').strip()
    password1 = request.data.get('password1', '').strip()
    password2 = request.data.get('password2', '').strip()
    full_name = request.data.get('full_name', '').strip()

    if password1 != password2:
        return Response({"error":_("passwords doesn't match")},status=status.HTTP_400_BAD_REQUEST)
      

    if models.User.objects.filter(email=email).exists():
        return Response({"error":_("Registeration failed,Try again")},status=status.HTTP_400_BAD_REQUEST)


    try:
        user = models.User.objects.create_user(
        full_name = full_name,
        email = email,
        password= password1,
        )

        return Response({"message":_("user created")},status=status.HTTP_201_CREATED)
    
    except:
        return Response({"error":_("error occurred try again")})

@api_view(['POST'])
@permission_classes([AllowAny])
def logout(request):
    refresh_token = request.data.get('refresh')
    if not refresh_token:
        return Response({"error": _("Refresh token required")}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response({"message": _("Logout successful")}, status=status.HTTP_205_RESET_CONTENT)
    except Exception:
        return Response({"error": _("Invalid token")}, status=status.HTTP_400_BAD_REQUEST)
    

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    return Response({
        "is_admin": user.is_staff,
    })

##################################


### products
class ProductPagination(PageNumberPagination):
    page_size = 12  # Default items per page
    page_size_query_param = 'page_size' # Frontend can override: /products/?page_size=50
    max_page_size = 100

    
@api_view(['GET'])
@permission_classes([AllowAny])
def get_all_products(request):
    
    # 1. Check if an Admin is requesting to see ALL items (including inactive)
    show_inactive = request.query_params.get('all') == 'true' and request.user.is_staff
    
    if show_inactive:
        # ADMIN VIEW: Show everything
        queryset = models.Product.objects.annotate(
            lowest_price=Min('variants__price'),
            highest_price=Max('variants__price'),
            average_rating=Avg('reviews__rating'),
            review_count=Count('reviews', distinct=True)
        ).prefetch_related('categories',
            Prefetch('variants', queryset=models.ProductVariant.objects.prefetch_related('images'))
        )
    else:
        # CUSTOMER VIEW: Hide inactive products and variants
        queryset = models.Product.objects.filter(is_active=True).annotate(
            lowest_price=Min('variants__price'),
            highest_price=Max('variants__price'),
            average_rating=Avg('reviews__rating'),
            review_count=Count('reviews', distinct=True)
        ).prefetch_related('categories',
            Prefetch('variants', queryset=models.ProductVariant.objects.filter(is_active=True).prefetch_related('images'))
        )

    # 2. FILTERING LOGIC 
    search_query = request.query_params.get('search', None)
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query) | 
            Q(description__icontains=search_query)
        )

    category = request.query_params.get('category', None)
    if category:
        category_list = [cat.strip() for cat in category.split(',')]
        for cat in category_list:
            queryset = queryset.filter(categories__name__iexact=cat, categories__is_active=True)
        queryset = queryset.distinct()

    min_price = request.query_params.get('min_price', None)
    max_price = request.query_params.get('max_price', None)

    try:
        if min_price is not None:
            min_price = float(min_price)
            queryset = queryset.filter(lowest_price__gte=min_price)
        if max_price is not None:
            max_price = float(max_price)
            queryset = queryset.filter(lowest_price__lte=max_price)
    except ValueError:
        return Response({"error": _("Invalid price format. Must be a number.")}, status=status.HTTP_400_BAD_REQUEST)

    sales_subquery = models.OrderItem.objects.filter(
        variant__product_id=OuterRef('pk')
    ).values('variant__product_id').annotate(
        total=Sum('quantity')
    ).values('total')

    queryset = queryset.annotate(
        sales_count=Coalesce(Subquery(sales_subquery), Value(0))
    )

    # 3. Apply Pagination
    queryset = queryset.order_by('-created_at')
    paginator = ProductPagination()
    result_page = paginator.paginate_queryset(queryset, request)
    
    serializer = serializers.GetAllProductListSerializer(result_page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_product_detail(request, pk):
    try:
        # 1. Check if an Admin is requesting to see ALL data (including inactive)
        show_inactive = request.query_params.get('all') == 'true' and request.user.is_staff

        if show_inactive:
            # ADMIN VIEW: Fetch the product and ALL of its variants, even if deactivated
            product = models.Product.objects.prefetch_related(
                'categories',
                Prefetch('variants', queryset=models.ProductVariant.objects.select_related('product').prefetch_related('images', 'product__categories'))
            ).get(pk=pk) # <-- Removed is_active=True here
            serializer = serializers.DashboardProductDetailSerializer(product)
            
        else:
            # CUSTOMER VIEW: Strictly filter for active product and active variants
            product = models.Product.objects.prefetch_related(
                'categories',
                Prefetch('variants', queryset=models.ProductVariant.objects.filter(is_active=True).select_related('product').prefetch_related('images', 'product__categories'))
            ).get(pk=pk, is_active=True)
            serializer = serializers.ProductDetailSerializer(product)

        return Response(serializer.data)

    except models.Product.DoesNotExist:
        return Response({"error": _("Product not found")}, status=404)
###
@api_view(['GET'])
@permission_classes([AllowAny])
def get_best_sellers(request):
    """
    Returns the explicitly marked BEST SELLER products for the homepage.
    """
    queryset = models.Product.objects.filter(
        is_active=True, 
        is_bestseller=True
    ).annotate(
        lowest_price=Min('variants__price'),
        highest_price=Max('variants__price'),
        average_rating=Avg('reviews__rating'),
        review_count=Count('reviews', distinct=True)
    ).prefetch_related('categories',
        Prefetch('variants', queryset=models.ProductVariant.objects.filter(is_active=True).prefetch_related('images'))
    )[:16]  # Get up to 16 best sellers

    serializer = serializers.GetAllProductListSerializer(queryset, many=True)
    return Response(serializer.data)



@api_view(['GET'])
@permission_classes([AllowAny])
def get_top_selling_product_overall(request):
    """
    Returns the absolute best-selling product based on historic order item sales,
    including its variant details.
    """
    sales_subquery = models.OrderItem.objects.filter(
        variant__product_id=OuterRef('pk')
    ).values('variant__product_id').annotate(
        total=Sum('quantity')
    ).values('total')

    top_product = models.Product.objects.filter(is_active=True).annotate(
        sales_count=Coalesce(Subquery(sales_subquery), Value(0))
    ).order_by('-sales_count').prefetch_related(
        'categories',
        Prefetch('variants', queryset=models.ProductVariant.objects.filter(is_active=True).select_related('product').prefetch_related('images', 'product__categories'))
    ).first()

    if not top_product:
        return Response({"error": _("No products found")}, status=status.HTTP_404_NOT_FOUND)

    serializer = serializers.ProductDetailSerializer(top_product)
    return Response(serializer.data)


############################# Cart

## HELPER FUNCTION
def get_cart_from_request(request):
    """Helper to fetch or create a cart based on User Auth or Device ID."""
    prefetch = Prefetch('items', queryset=models.CartItem.objects.select_related('variant__product').prefetch_related('variant__images', 'variant__product__categories'))
    if request.user.is_authenticated:
        cart = models.Cart.objects.prefetch_related(prefetch).filter(customer=request.user).first()
        if not cart:
            cart = models.Cart.objects.create(customer=request.user)
        return cart
    else:
        device_id = request.headers.get('X-Device-ID')
        if not device_id:
            raise ValueError(_("No Device ID provided for guest cart."))
        
        cart = models.Cart.objects.prefetch_related(prefetch).filter(device_id=device_id, customer__isnull=True).first()
        if not cart:
            cart = models.Cart.objects.create(device_id=device_id)
        return cart

@api_view(['GET'])
@permission_classes([AllowAny])
def get_cart(request):
    try:
        cart = get_cart_from_request(request)
        serializer = serializers.CartSerializer(cart)
        return Response(serializer.data)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)


@api_view(['POST'])
@permission_classes([AllowAny])
def add_to_cart(request):
    try:
        cart = get_cart_from_request(request)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    variant_id = request.data.get('variant_id')
    quantity = int(request.data.get('quantity', 1))

    try:
        variant = models.ProductVariant.objects.get(id=variant_id, is_active=True)
    except models.ProductVariant.DoesNotExist:
        return Response({"error": _("Product variant not found.")}, status=status.HTTP_404_NOT_FOUND)

    # 1. Get current quantity in cart
    try:
        cart_item = models.CartItem.objects.get(cart=cart, variant=variant)
        current_in_cart = cart_item.quantity
    except models.CartItem.DoesNotExist:
        cart_item = None
        current_in_cart = 0

    # 2. Check Stock
    total_needed = current_in_cart + quantity
    if total_needed > variant.stock:
        left = variant.stock - current_in_cart
        left = max(left, 0)
        return Response(
            {"error": _("No enough stock for this item.")},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 3. Create or Update
    if cart_item:
        cart_item.quantity += quantity
        cart_item.price = variant.price
        cart_item.save()
    else:
        models.CartItem.objects.create(
            cart=cart,
            variant=variant,
            quantity=quantity,
            price=variant.price
        )

    cart = get_cart_from_request(request)
    return Response(serializers.CartSerializer(cart).data, status=200)


@api_view(['PATCH'])
@permission_classes([AllowAny])
def update_cart_item(request, item_id):
    try:
        cart = get_cart_from_request(request)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    try:
        cart_item = models.CartItem.objects.get(id=item_id, cart=cart)
    except models.CartItem.DoesNotExist:
        return Response({"error": _("Cart item not found.")}, status=status.HTTP_404_NOT_FOUND)
    new_quantity = int(request.data.get('quantity', 1))

    if new_quantity < 1:
        cart_item.delete()
        return Response({"message": _("Item removed")}, status=200)

    if cart_item.variant.stock < new_quantity:
        return Response({"error": _("Exceeds available stock")}, status=400)

    cart_item.quantity = new_quantity
    cart_item.save()
    
    cart = get_cart_from_request(request)
    return Response(serializers.CartSerializer(cart).data)


@api_view(['DELETE'])
@permission_classes([AllowAny])
def remove_from_cart(request, item_id):
    try:
        cart = get_cart_from_request(request)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    try:
        cart_item = models.CartItem.objects.get(id=item_id, cart=cart)
    except models.CartItem.DoesNotExist:
        return Response({"error": _("Cart item not found.")}, status=status.HTTP_404_NOT_FOUND)
    cart_item.delete()
    
    cart = get_cart_from_request(request)
    return Response(serializers.CartSerializer(cart).data)


@api_view(['DELETE'])
@permission_classes([AllowAny])
def clear_cart(request):
    try:
        cart = get_cart_from_request(request)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    cart.items.all().delete()
    return Response({"message": _("All items removed from cart")}, status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def merge_cart(request):
    device_id = request.data.get('device_id')
    
    # 1. Merge Orders & Payments by Device ID
    if device_id:
        guest_orders_by_device = models.Order.objects.filter(device_id=device_id, customer__isnull=True)
        if guest_orders_by_device.exists():
            models.Payment.objects.filter(order__in=guest_orders_by_device).update(customer=request.user)
            guest_orders_by_device.update(customer=request.user)
            
    # 2. Merge Orders & Payments by User Email
    if request.user.email:
        guest_orders_by_email = models.Order.objects.filter(guest_email__iexact=request.user.email, customer__isnull=True).exclude(guest_email="")
        if guest_orders_by_email.exists():
            models.Payment.objects.filter(order__in=guest_orders_by_email).update(customer=request.user)
            guest_orders_by_email.update(customer=request.user)

    if not device_id:
        return Response({"message": _("Orders merged. No guest cart to merge.")}, status=200)

    guest_cart = models.Cart.objects.filter(device_id=device_id, customer__isnull=True).first()
    if not guest_cart:
        return Response({"message": _("Guest cart not found or already merged")}, status=200)

    user_cart = models.Cart.objects.filter(customer=request.user).first()
    if not user_cart:
        user_cart = models.Cart.objects.create(customer=request.user)

    for guest_item in guest_cart.items.select_related('variant'):
        user_item, created = models.CartItem.objects.get_or_create(
            cart=user_cart,
            variant=guest_item.variant,
            defaults={'quantity': guest_item.quantity, 'price': guest_item.variant.price}
        )
        
        if not created:
            new_quantity = user_item.quantity + guest_item.quantity
            if new_quantity > guest_item.variant.stock:
                user_item.quantity = guest_item.variant.stock
            else:
                user_item.quantity = new_quantity
            
            user_item.price = guest_item.variant.price
            user_item.save()

    guest_cart.delete()
    return Response({"message": _("Carts merged successfully!")}, status=200)


#############################


###### Orders

@api_view(['POST'])
@permission_classes([AllowAny])
@transaction.atomic
def place_order(request):
    is_authenticated = request.user.is_authenticated
    device_id = request.headers.get('X-Device-ID')

    # --- 0. Resolve Cart (authenticated user or guest via device-ID) ---
    try:
        if is_authenticated:
            cart = models.Cart.objects.select_for_update().get(customer=request.user)
        else:
            if not device_id:
                return Response({"error": _("Device ID is required for guest checkout.")}, status=status.HTTP_400_BAD_REQUEST)
            cart = models.Cart.objects.select_for_update().get(device_id=device_id, customer__isnull=True)
    except models.Cart.DoesNotExist:
        return Response({"error": _("Cart not found.")}, status=status.HTTP_404_NOT_FOUND)

    if not cart.items.exists():
        return Response({"error": _("Cart is empty")}, status=400)
        
    # Prevent double submission from quick multiple clicks
    if is_authenticated:
        recent_order = models.Order.objects.filter(
            customer=request.user,
            created_at__gte=timezone.now() - timedelta(seconds=10)
        ).exists()
    else:
        # This is important
        # For guests, check by phone number + time window
        phone = request.data.get('phone_number', '')
        recent_order = models.Order.objects.filter(
            customer__isnull=True,
            phone_number=phone,
            created_at__gte=timezone.now() - timedelta(seconds=10)
        ).exists() if phone else False

    if recent_order:
        return Response(
            {"error": _("Please wait a moment before placing another order.")}, 
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    serializer = serializers.CreateOrderSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    # --- 1. THE PRE-CHECK LOOP (Validate BEFORE touching the database) ---
    prefetched_items = list(cart.items.select_related('variant__product'))
    for item in prefetched_items:
        variant = item.variant
        
        # Check if active
        if not variant.is_active or not variant.product.is_active:
            return Response(
                {"error": _("Sorry, {product_name} ({volume}) is no longer available.").format(product_name=variant.product.name, volume=variant.volume)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check stock
        if variant.stock < item.quantity:
            return Response(
                {"error": _("Product {product_name} is out of stock. Only {stock} left.").format(product_name=variant.product.name, stock=variant.stock)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    # --- 2. Read Payment Method ---
    payment_method = request.data.get('payment_method', 'card')

    # --- 2.5 Look up Governorate & lock in shipping fee ---
    governorate_id = serializer.validated_data.get('governorate_id')
    try:
        governorate = models.Governorate.objects.get(id=governorate_id, is_active=True)
    except models.Governorate.DoesNotExist:
        return Response(
            {"error": _("Selected governorate is not available for shipping.")},
            status=status.HTTP_400_BAD_REQUEST
        )

    # --- 3. SAFE TO CREATE ---
    order = models.Order.objects.create(
        customer=request.user if is_authenticated else None,
        full_name=serializer.validated_data['full_name'],
        full_address=serializer.validated_data['full_address'],
        phone_number=serializer.validated_data.get('phone_number'),
        country=serializer.validated_data.get('country'),
        order_notes=serializer.validated_data.get('order_notes'),
        guest_email=serializer.validated_data.get('guest_email', ''),
        device_id=device_id if not is_authenticated else None,
        governorate=governorate,
        shipping_fee=governorate.shipping_fee,
        status='pending'  # Temporary, will be updated below
    )

    # --- 4. CREATE ORDER ITEMS ---
    for item in prefetched_items:
        models.OrderItem.objects.create(
            order=order,
            variant=item.variant,
            quantity=item.quantity,
            price=item.price
        )

    # --- 5. COD vs ONLINE PAYMENT ---
    if payment_method == 'cod':
        # COD: Deduct stock, clear cart, create Payment, keep status "pending"
        from base.services import StockService
        for item in prefetched_items:
            item.variant.stock = F('stock') - item.quantity
            item.variant.save()
            item.variant.refresh_from_db()
            StockService.check_and_notify_low_stock(item.variant)

        cart.items.all().delete()

        models.Payment.objects.create(
            customer=request.user if is_authenticated else None,
            order=order,
            amount=order.total_price,
            method='cod',
            transaction_id=f"COD-{order.id}"
        )

        order.status = 'pending'
        order.save()
        order_price = order.total_price-order.shipping_fee
        customer_label = order.full_name if is_authenticated else f"{order.full_name} (Guest)"
        payment_method = "كاش عند الاستلام"
        guest_email_line = f"📧 <b>Guest Email(إيميل الضيف):</b> {order.guest_email}\n" if order.guest_email else ""
        message = (
            f"🚨 <b>NEW ORDER RECEIVED!</b> 🚨\n\n"
            f"🛒 <b>Order ID(رقم الطلب):</b> #{order.id}\n"
            f"👤 <b>Customer(العميل):</b> {customer_label}\n"
            f"👤 <b>Customer Number(رقم العميل):</b> {order.phone_number}\n"
            f"👤 <b>Customer Address(عنوان العميل):</b> {order.full_address}\n"
            f"👤 <b>Order Notes(ملاحظات الطلب):</b> {order.order_notes}\n"
            f"{guest_email_line}"
            f"👤 <b>Order Price(سعر الطلب):</b> {order_price}\n"
            f"👤 <b>Shipping Fee(سعر الشحن):</b> {order.shipping_fee}\n"
            f"💵 <b>Total(المبلغ):</b> {order.total_price} EGP\n"
            f"💳 <b>Payment(طريقة الدفع):</b> {payment_method}\n\n"
        )
        send_telegram_notification(message)

        return Response({
            "message": _("Order placed successfully"),
            "order_id": order.id,
            "next_step": "success_page"
        }, status=201)

    else:
        # ONLINE PAYMENT: Don't touch stock or cart yet — wait for payment gateway callback
        order.status = 'awaiting_payment'
        order.save()

        return Response({
            "message": _("Order initiated"),
            "order_id": order.id,
            "next_step": "payment_gateway"
        }, status=201)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_my_orders(request):
    """List all past orders for the logged-in user or guest (Optimized)."""
    
    items_prefetch = Prefetch(
        'items', 
        queryset=models.OrderItem.objects.select_related('variant__product')
    )

    # 2. Main Query
    if request.user.is_authenticated:
        orders = models.Order.objects.filter(customer=request.user)\
            .order_by('-created_at')\
            .select_related('governorate')\
            .prefetch_related(items_prefetch) # <--- This magic line fixes the N+1
    else:
        device_id = request.headers.get('X-Device-ID')
        if not device_id:
            return Response({"error": _("Device ID is required to fetch guest orders.")}, status=400)
            
        orders = models.Order.objects.filter(device_id=device_id, customer__isnull=True)\
            .order_by('-created_at')\
            .select_related('governorate')\
            .prefetch_related(items_prefetch)

    serializer = serializers.OrderSerializer(orders, many=True)
    return Response(serializer.data)

################


############################# Reviews

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_review(request):
    """
    User adds a review. 
    Expects: { "product": 1, "rating": 5, "comment": "Great!" }
    """
    serializer = serializers.CreateReviewSerializer(
        data=request.data, 
        context={'request': request}
    )
    
    if serializer.is_valid():
        try:
            serializer.save(customer=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({"error": _("You have already reviewed this product.")}, status=400)
            
    return Response(serializer.errors, status=400)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_product_reviews(request, product_id):
    """Get all reviews for a specific product."""
    reviews = models.Review.objects.filter(product_id=product_id).select_related('customer')
    serializer = serializers.ReviewSerializer(reviews, many=True)
    return Response(serializer.data)


############################# Wishlist

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_wishlist(request):
    """
    Get current user's wishlist.
    Optimized: Prefetches products -> variants -> images for the cards.
    """
    try:
        # We need to prefetch the same things GetAllProductListSerializer needs
        # (variants, lowest price, images, etc)
        wishlist = models.WishList.objects.prefetch_related(
            Prefetch('products', queryset=models.Product.objects.filter(is_active=True).annotate(
                lowest_price=Min('variants__price'),
                highest_price=Max('variants__price'),
                average_rating=Avg('reviews__rating'),
                review_count=Count('reviews', distinct=True)
            ).prefetch_related(
                'categories',
                Prefetch('variants', queryset=models.ProductVariant.objects.filter(is_active=True).prefetch_related('images'))
            ))
        ).get(customer=request.user)
        
        serializer = serializers.WishlistSerializer(wishlist)
        return Response(serializer.data)
        
    except models.WishList.DoesNotExist:
        # Return empty structure if no wishlist exists yet
        return Response({"products": []})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_wishlist(request):
    """
    Add or Remove item from wishlist. Acts as a toggle.
    Expects: { "product_id": 5 }
    """
    product_id = request.data.get('product_id')
    try:
        product = models.Product.objects.get(id=product_id)
    except models.Product.DoesNotExist:
        return Response({"error": _("Product not found.")}, status=status.HTTP_404_NOT_FOUND)
    
    wishlist = models.WishList.objects.filter(customer=request.user).first()
    if not wishlist:
        wishlist = models.WishList.objects.create(customer=request.user)
    
    if product in wishlist.products.all():
        wishlist.products.remove(product)
        return Response({"message": _("Removed from wishlist"), "added": False})
    else:
        wishlist.products.add(product)
        return Response({"message": _("Added to wishlist"), "added": True})




############## Payment Helpers #############

def get_order_for_payment(request, order_id):
    """Fetch an order verifying ownership for both authenticated and guest users."""
    if request.user.is_authenticated:
        return models.Order.objects.select_related('governorate').prefetch_related(
            Prefetch('items', queryset=models.OrderItem.objects.select_related('variant__product'))
        ).get(id=order_id, customer=request.user)
    else:
        device_id = request.headers.get('X-Device-ID')
        if not device_id:
            raise models.Order.DoesNotExist
        return models.Order.objects.select_related('governorate').prefetch_related(
            Prefetch('items', queryset=models.OrderItem.objects.select_related('variant__product'))
        ).get(id=order_id, device_id=device_id, customer__isnull=True)

def clear_cart_for_order(order):
    """Clear the correct cart after payment — by customer or device_id."""
    if order.customer:
        models.Cart.objects.filter(customer=order.customer).delete()
    elif order.device_id:
        models.Cart.objects.filter(device_id=order.device_id, customer__isnull=True).delete()


############## Payment Integration (Paymob) #############
import hmac
import hashlib

@api_view(['POST'])
@permission_classes([AllowAny])
def paymob_checkout(request):
    order_id = request.data.get('order_id')
    payment_method = request.data.get('payment_method', 'card')
    
    if not order_id:
        return Response({"error": _("order_id is required")}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        order = get_order_for_payment(request, order_id)
    except models.Order.DoesNotExist:
        return Response({"error": _("Order not found")}, status=status.HTTP_404_NOT_FOUND)
        
    if order.status != 'awaiting_payment':
        return Response(
            {"error": _("This order cannot be paid online or is already processed.")}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    amount_cents = int(order.total_price * 100)
    
    name_parts = order.full_name.split() if order.full_name else ['Guest']
    billing_email = (request.user.email if request.user.is_authenticated else order.guest_email) or 'na@na.com'
    billing_data = {
        "apartment": "NA", 
        "email": billing_email, 
        "floor": "NA", 
        "first_name": name_parts[0],
        "street": order.full_address or "NA", 
        "building": "NA", 
        "phone_number": order.phone_number or "NA", 
        "shipping_method": "NA", 
        "postal_code": "NA", 
        "city": "NA", 
        "country": order.country or "EG", 
        "last_name": name_parts[-1] if len(name_parts) > 1 else "Guest", 
        "state": "NA"
    }

    integration_id = getattr(settings, 'PAYMOB_WALLET_INTEGRATION_ID', None) if payment_method == 'wallet' else settings.PAYMOB_INTEGRATION_ID
    if payment_method == 'wallet' and not integration_id:
        return Response({"error": _("Wallet integration is not configured")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    items = []
    for item in order.items.all():
        product_name = item.variant.product.name if hasattr(item, 'variant') else getattr(item, 'product', item).name if hasattr(item, 'product') else "Product"
        items.append({
            "name": product_name,
            "amount": int(item.price * 100),
            "description": product_name,
            "quantity": item.quantity
        })
        
    if order.shipping_fee and order.shipping_fee > 0:
        shipping_desc = f"Shipping to {order.governorate.name}" if order.governorate else "Shipping Fee"
        items.append({
            "name": "Shipping Fee",
            "amount": int(order.shipping_fee * 100),
            "description": shipping_desc,
            "quantity": 1
        })

    payload = {
        "amount": amount_cents,
        "currency": "EGP",
        "payment_methods": [int(integration_id)] if integration_id else [],
        "items": items,
        "billing_data": billing_data,
        "special_reference": f"{order.id}~{int(time.time())}"
    }

    headers = {
        "Authorization": f"Token {settings.PAYMOB_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    intention_response = requests.post(
        "https://accept.paymob.com/v1/intention/",
        json=payload,
        headers=headers
    )
    
    if not intention_response.ok:
        # return Response(intention_response.json())
        return Response({"error": _("Failed to create payment intention with Paymob")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    client_secret = intention_response.json().get('client_secret')
    if not client_secret:
        return Response({"error": _("Failed to retrieve client secret from Paymob")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    checkout_url = f"https://accept.paymob.com/unifiedcheckout/?publicKey={settings.PAYMOB_PUBLIC_KEY}&clientSecret={client_secret}"

    return Response({
        "url": checkout_url
    })
@api_view(['POST']) 
@permission_classes([AllowAny])
def paymob_webhook(request):
    hmac_received = request.query_params.get('hmac')
    if not hmac_received:
        return Response({"error": _("HMAC signature missing")}, status=status.HTTP_400_BAD_REQUEST)
        
    data = request.data
    obj = data.get('obj', {})
    
    order_id = ""
    order_dict = obj.get('order', {})
    if isinstance(order_dict, dict):
        order_id = order_dict.get('id', '')
    elif isinstance(order_dict, int):
        order_id = order_dict
        
    source_data = obj.get('source_data', {})
    
    def format_bool(val):
        if isinstance(val, bool):
            return str(val).lower()
        return str(val)
        
    concatenated = (
        format_bool(obj.get('amount_cents', '')) + 
        format_bool(obj.get('created_at', '')) + 
        format_bool(obj.get('currency', '')) + 
        format_bool(obj.get('error_occured', '')) + 
        format_bool(obj.get('has_parent_transaction', '')) + 
        format_bool(obj.get('id', '')) + 
        format_bool(obj.get('integration_id', '')) + 
        format_bool(obj.get('is_3d_secure', '')) + 
        format_bool(obj.get('is_auth', '')) + 
        format_bool(obj.get('is_capture', '')) + 
        format_bool(obj.get('is_refunded', '')) + 
        format_bool(obj.get('is_standalone_payment', '')) + 
        format_bool(obj.get('is_voided', '')) + 
        format_bool(order_id) + 
        format_bool(obj.get('owner', '')) + 
        format_bool(obj.get('pending', '')) + 
        format_bool(source_data.get('pan', '')) + 
        format_bool(source_data.get('sub_type', '')) + 
        format_bool(source_data.get('type', '')) + 
        format_bool(obj.get('success', ''))
    )
    
    calculated_hmac = hmac.new(
        settings.PAYMOB_HMAC_SECRET.encode('utf-8'),
        concatenated.encode('utf-8'),
        hashlib.sha512
    ).hexdigest()
    
    if calculated_hmac != hmac_received:
        print("HMAC Mismatch!")
        return Response({"error": _("Invalid HMAC signature")}, status=status.HTTP_401_UNAUTHORIZED)
        
    if obj.get('success') == True:
        special_ref = obj.get('special_reference') or obj.get('payment_key_claims', {}).get('extra', {}).get('special_reference') or ''
        merchant_order_id = order_dict.get('merchant_order_id', '') if isinstance(order_dict, dict) else ''
        
        reference = special_ref or merchant_order_id
        django_order_id = reference.split('~')[0] if '~' in reference else reference
        
        if django_order_id:
            try:
                with transaction.atomic():
                    order = models.Order.objects.select_for_update().get(id=django_order_id)
                    
                    if order.status != 'paid':
                        order.status = 'paid'
                        order.save()
                        
                        from base.services import StockService
                        for item in order.items.select_related('variant'):
                            item.variant.stock = F('stock') - item.quantity
                            item.variant.save()
                            item.variant.refresh_from_db()
                            StockService.check_and_notify_low_stock(item.variant)
                            
                        clear_cart_for_order(order)
                        
                        models.Payment.objects.create(
                            customer=order.customer,
                            order=order,
                            amount=Decimal(obj.get('amount_cents', 0)) / 100,
                            method='paymob',
                            transaction_id=str(obj.get('id'))
                        )
                        order_price = order.total_price-order.shipping_fee
                        message = (
            f"🚨 <b>NEW ORDER RECEIVED!</b> 🚨\n\n"
            f"🛒 <b>Order ID(رقم الطلب):</b> #{order.id}\n"
            f"👤 <b>Customer(العميل):</b> {order.full_name}\n"
            f"👤 <b>Customer Number(رقم العميل):</b> {order.phone_number}\n"
            f"👤 <b>Customer Address(عنوان العميل):</b> {order.full_address}\n"
            f"👤 <b>Order Notes(ملاحظات الطلب):</b> {order.order_notes}\n"
            f"👤 <b>Order Price(سعر الطلب):</b> {order_price}\n"
            f"👤 <b>Shipping Fee(سعر الشحن):</b> {order.shipping_fee}\n"
            f"💵 <b>Total(المبلغ):</b> {order.total_price} EGP\n"
            f"💳 <b>Payment(طريقة الدفع):</b> {order.payment.method}\n\n"
                        )
                        send_telegram_notification(message)
                        print(f"✅ Order {django_order_id} fully processed via Paymob.")
            except models.Order.DoesNotExist:
                print(f"❌ Order {django_order_id} not found during Paymob webhook.")
            except Exception as e:
                print(f"❌ Webhook Error: {str(e)}")
                return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
    return Response({"message": _("Webhook received successfully")}, status=status.HTTP_200_OK)############### DASHBOARD ##################

## ADD SOMETHINGS ##

from rest_framework.permissions import IsAdminUser

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def manage_categories(request):
    
    # --- GET: The frontend asks for the full list for the dropdown ---
    if request.method == 'GET':
        # If admin requests all=true, show inactive too
        show_all = request.query_params.get('all') == 'true' and request.user.is_staff
        if show_all:
            categories = models.Category.objects.all().order_by('name')
            serializer = serializers.DashboardCategorySerializer(categories, many=True)
        else:
            categories = models.Category.objects.filter(is_active=True).order_by('name')
            serializer = serializers.CategorySerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # --- POST: The admin types a new name and hits "Save" ---
    elif request.method == 'POST':
        if not request.user.is_staff:
            return Response({"error":_("You can't perform this action")},status=status.HTTP_403_FORBIDDEN)
        serializer = serializers.DashboardCategorySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def manage_category_detail(request, pk):
    """Admin endpoint to edit or soft-delete a category."""
    try:
        category = models.Category.objects.get(id=pk)
    except models.Category.DoesNotExist:
        return Response({"error": _("Category not found.")}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PATCH':
        serializer = serializers.DashboardCategorySerializer(category, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": _("Category updated"), "data": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        is_hard_delete = request.query_params.get('hard') == 'true'

        if is_hard_delete:
            # Safety: check if any product uses this category
            if category.products.exists():
                return Response(
                    {"error": _("Cannot delete this category because it is assigned to products. Please deactivate it instead.")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            category.delete()
            return Response({"message": _("Category permanently deleted.")}, status=status.HTTP_200_OK)
        else:
            # Soft delete
            category.is_active = False
            category.save()
            return Response({"message": _("Category deactivated successfully.")}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAdminUser]) # 1. Must be at least Staff
def promote_user_to_admin(request):
    """
    Promotes a customer to Staff status.
    ONLY a Superuser can do this to prevent 'coups'.
    """
    # 2. Security Check: Are YOU a superuser?
    if not request.user.is_superuser:
        return Response(
            {"error": _("Only Superusers can promote other users to Admin.")},
            status=status.HTTP_403_FORBIDDEN
        )

    email = request.data.get('email')
    try:
        user = models.User.objects.get(email=email)
    except models.User.DoesNotExist:
        return Response({"error": _("User with this email not found.")}, status=status.HTTP_404_NOT_FOUND)
    # 3. Promote
    if user.is_staff == False:
        user.is_staff = True
        user.save()
    else:
        return Response({"message":_("User is already an admin (Staff)")},status=status.HTTP_400_BAD_REQUEST)

    return Response({"message": _("{user_name} is now an Admin (Staff).").format(user_name=user.full_name)})



@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_latest_orders(request):
    orders = (
    models.Order.objects
    .select_related('customer', 'payment', 'governorate') # fixes customer.email
    .prefetch_related(
        Prefetch(
            'items',
            queryset=models.OrderItem.objects.select_related('variant__product')
        )
    )
    .exclude(status='awaiting_payment')
    .order_by('-created_at')
)

    search_query = request.query_params.get('search', None)
    if search_query:
        orders = orders.filter(
            Q(customer__email__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(id__icontains=search_query) |
            Q(full_name__icontains=search_query)
        )

    status_query = request.query_params.get('status', None)
    if status_query:
        orders = orders.filter(status__iexact=status_query)
    paginator = PageNumberPagination()
    paginator.page_size = 10  # Set how many orders you want per page
    
    # 3. Create the "Page" (slice the queryset based on the URL ?page=x)
    result_page = paginator.paginate_queryset(orders, request)

    # 4. Serialize ONLY the data for the current page
    serializer = serializers.DashBoardOrderSerializer(result_page, many=True)

    # 5. Return the response with pagination metadata (Next, Previous, Count)
    return paginator.get_paginated_response(serializer.data)



@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_all_orders_num(request):
    # This runs ONE query instead of SIX
    data = models.Order.objects.aggregate(
        orders=Count('id'),
        pending=Count('id', filter=Q(status='pending')),
        paid=Count('id', filter=Q(status='paid')),
        delivered=Count('id', filter=Q(status='delivered')),
        shipped=Count('id', filter=Q(status='shipped')),
        cancelled=Count('id', filter=Q(status='cancelled')),
    )
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_dashboard_stats(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    # 1. Total Sales
    total_sales = models.Payment.objects.aggregate(total=Sum('amount'))['total'] or 0
    
    revenue_stats = {
        "today": models.Payment.objects.filter(created_at__gte=today_start).aggregate(total=Sum('amount'))['total'] or 0,
        "this_week": models.Payment.objects.filter(created_at__gte=week_start).aggregate(total=Sum('amount'))['total'] or 0,
        "this_month": models.Payment.objects.filter(created_at__gte=month_start).aggregate(total=Sum('amount'))['total'] or 0,
        "all_time": total_sales,
    }

    # 2. Total Products & Stock (One query)
    product_stats = models.Product.objects.aggregate(
        count=Count('id'),
        total_stock=Sum('variants__stock')
    )
    
    # 3. Total Users
    users_count = models.User.objects.count()
    
    # 4. Order Stats (The optimized query from above)
    order_stats = models.Order.objects.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status='pending')),
        paid=Count('id', filter=Q(status='paid')), # Example
        delivered=Count('id', filter=Q(status='delivered')),
        shipped=Count('id', filter=Q(status='shipped')),
        cancelled=Count('id', filter=Q(status='cancelled')),
        refunded=Count('id', filter=Q(status='refunded')),
        # ... add others
    )

    # 5. Out of stock variants
    out_of_stock_count = models.ProductVariant.objects.filter(stock=0).count()
    
    # 6. Total Categories
    categories_count = models.Category.objects.count()

    # 7. Total Reviews
    reviews_count = models.Review.objects.count()

    return Response({
        "sales": total_sales,
        "revenue_stats": revenue_stats,
        "products": product_stats,
        "users": users_count,
        "orders": order_stats,
        "out_of_stock": out_of_stock_count,
        "categories": categories_count,
        "reviews": reviews_count
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_all_reviews(request):
    # 1. Fix the query: select_related (for ForeignKeys) + order_by (Required for pagination)
    reviews = models.Review.objects.select_related('customer', 'product').order_by('-created_at')
    
    # 2. Initialize the Paginator
    paginator = PageNumberPagination()
    paginator.page_size = 10  # You can adjust how many reviews per page here
    
    # 3. Slice the queryset based on the page the frontend requested
    paginated_reviews = paginator.paginate_queryset(reviews, request)
    
    # 4. Serialize ONLY the 20 reviews on this specific page
    serializer = serializers.DashBoardReviewSerializer(paginated_reviews, many=True)
    
    # 5. Return the special paginated response
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def order_detail_action(request, pk):
    try:
        order = models.Order.objects.select_related('customer', 'governorate', 'payment').prefetch_related(
            Prefetch('items', queryset=models.OrderItem.objects.select_related('variant__product'))
        ).get(id=pk)
    except models.Order.DoesNotExist:
        return Response({"error": _("Order not found.")}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = serializers.DashBoardOrderSerializer(order)
        return Response({'data': serializer.data})

    elif request.method == 'PATCH':
        serializer = serializers.DashBoardOrderStatusSerializer(order, data=request.data, partial=True)
        if serializer.is_valid():
            new_status = serializer.validated_data.get('status')

            # Restore stock when refunding or cancelling
            if new_status in ('refunded', 'cancelled'):
                # Only restore if:
                # 1. The OLD status wasn't already refunded or cancelled (prevent double restoration)
                # 2. The order wasn't stuck in 'awaiting_payment' (where stock is never deducted)
                if order.status not in ('refunded', 'cancelled', 'awaiting_payment'):
                    for item in order.items.select_related('variant'):
                        if item.variant:
                            item.variant.stock = F('stock') + item.quantity
                            item.variant.save()

            serializer.save()
            return Response({'message': _('Status updated'), 'status': order.status})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

#######################

@api_view(['POST'])
@permission_classes([IsAdminUser]) # Protect your dashboard!
def create_product_api(request):
    """
    Creates the main product entry (Name, Description, Category).
    Does NOT handle variants or images yet.
    """
    # We use the serializer just for validation and saving the base fields
    serializer = serializers.DashboardProductCreateSerializer(data=request.data)
    
    if serializer.is_valid():
        product = serializer.save()
        
        # Return the ID so the frontend knows where to attach variants next
        return Response({
            "message": _("Product created successfully"),
            "product_id": product.id,
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)
        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------
# STEP 2: Add Variants (Supports Bulk Creation)
# ---------------------------------------------------------
@api_view(['POST'])
@permission_classes([IsAdminUser])
def add_variants_to_product_api(request, product_id):
    try:
        product = models.Product.objects.get(id=product_id)
    except models.Product.DoesNotExist:
        return Response({"error": _("Product not found.")}, status=status.HTTP_404_NOT_FOUND)
    
    # Check if bulk or single
    is_many = isinstance(request.data, list)
    
    # Pass context so the serializer knows which product to attach to
    serializer = serializers.DashboardVariantCreateSerializer(
        data=request.data, 
        many=is_many,
        context={'product_id': product.id} 
    )
    
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------
# STEP 3: Upload Image for a Specific Variant
# ---------------------------------------------------------
@api_view(['POST'])
@permission_classes([IsAdminUser])
@parser_classes([MultiPartParser, FormParser]) # Essential for handling file uploads
def upload_variant_image_api(request, variant_id):
    """
    Uploads a single image for a specific variant.
    Key in FormData should be 'img'.
    Optional Key 'is_thumbnail' (boolean string).
    """
    # 1. Get the variant
    try:
        variant = models.ProductVariant.objects.get(id=variant_id)
    except models.ProductVariant.DoesNotExist:
        return Response({"error": _("Product variant not found.")}, status=status.HTTP_404_NOT_FOUND)
    
    # 2. Check if file is present
    if 'img' not in request.FILES:
        return Response({"error": _("No image file provided (key 'img' missing).")}, status=400)

    is_thumbnail = request.data.get('is_thumbnail', 'false').lower() in ['true', '1', 'yes']

    # 3. Manual creation is often easier for simple file uploads than serializers
    try:
        image_file = request.FILES['img']
        
        # Create the image instance
        img_instance = models.ProductImage(
            variant=variant,
            img=image_file,
            is_thumbnail=is_thumbnail
        )
        img_instance.save() # This triggers the custom save method to handle existing thumbnails
        
        return Response({
            "message": _("Image uploaded"),
            "url": img_instance.img.url,
            "id": img_instance.id,
            "is_thumbnail": img_instance.is_thumbnail
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_variant_image_api(request, image_id):
    """
    Deletes a specific product image by ID.
    """
    try:
        image = models.ProductImage.objects.get(id=image_id)
    except models.ProductImage.DoesNotExist:
        return Response({"error": _("Product image not found.")}, status=status.HTTP_404_NOT_FOUND)
    image.delete()
    return Response({"message": _("Image deleted successfully.")}, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def set_variant_thumbnail_api(request, image_id):
    """
    Sets a specific image as the thumbnail.
    """
    try:
        image = models.ProductImage.objects.get(id=image_id)
    except models.ProductImage.DoesNotExist:
        return Response({"error": _("Product image not found.")}, status=status.HTTP_404_NOT_FOUND)
    image.is_thumbnail = True
    image.save() # Custom save logic automatically unchecks other images for this variant
    return Response({"message": _("Thumbnail set successfully.")}, status=status.HTTP_200_OK)

#### i will adjust after some shits

# --- PRODUCT EDIT & DEACTIVATE ---
@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def dashboard_product_detail_api(request, pk):
    try:
        product = models.Product.objects.get(id=pk)
    except models.Product.DoesNotExist:
        return Response({"error": _("Product not found.")}, status=status.HTTP_404_NOT_FOUND)

    # --- DELETE LOGIC ---
    if request.method == 'DELETE':
        
        # Check if the frontend requested a HARD delete
        is_hard_delete = request.query_params.get('hard') == 'true'

        if is_hard_delete:
            # 1. THE SAFETY GUARD: Has anyone bought any variant of this product?
            # We use the double underscore (variant__product) to look across the relationships
            if models.OrderItem.objects.filter(variant__product=product).exists():
                return Response(
                    {"error": _("Cannot hard delete this product because one or more of its variants exist in customer orders. Please deactivate it instead.")}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            # 2. Safe to Hard Delete
            product.delete()
            return Response({"message": _("Product permanently deleted.")}, status=status.HTTP_200_OK)
            
        else:
            # 3. Normal Soft Delete (Deactivate)
            product.is_active = False
            product.save()
            return Response({"message": _("Product deactivated successfully.")}, status=status.HTTP_200_OK)

    # --- EDIT LOGIC ---
    if request.method == 'PATCH':
        serializer = serializers.DashboardProductUpdateSerializer(
            instance=product, 
            data=request.data, 
            partial=True 
        )
        if serializer.is_valid():
            serializer.save()
            return Response({"message": _("Product updated"), "data": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- VARIANT EDIT & DEACTIVATE ---
@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def dashboard_variant_detail_api(request, variant_id):
    try:
        variant = models.ProductVariant.objects.get(id=variant_id)
    except models.ProductVariant.DoesNotExist:
        return Response({"error": _("Product variant not found.")}, status=status.HTTP_404_NOT_FOUND)

    # --- DELETE LOGIC ---
    if request.method == 'DELETE':
        
        # Check if the frontend requested a HARD delete
        is_hard_delete = request.query_params.get('hard') == 'true'

        if is_hard_delete:
            # 1. THE SAFETY GUARD: Has anyone bought this?
            if models.OrderItem.objects.filter(variant=variant).exists():
                return Response(
                    {"error": _("Cannot hard delete this variant because it exists in customer orders. Please deactivate it instead.")}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 2. Safe to Hard Delete
            variant.delete()
            return Response({"message": _("Variant permanently deleted.")}, status=status.HTTP_200_OK)
            
        else:
            # 3. Normal Soft Delete (Deactivate)
            variant.is_active = False
            variant.save()
            return Response({"message": _("Variant deactivated successfully.")}, status=status.HTTP_200_OK)

    # --- EDIT LOGIC ---
    if request.method == 'PATCH':
        serializer = serializers.DashboardVariantUpdateSerializer(
            instance=variant, 
            data=request.data, 
            partial=True
        )
        if serializer.is_valid():
            serializer.save()
            return Response({"message": _("Variant updated"), "data": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


########### Dashboard Charts
# ---------------------------------------------------------
# 1. LOW STOCK PRODUCTS
# ---------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_low_chart_info(request):
    """
    Returns specific VARIANTS that are low in stock (<= 20).
    Sorted by lowest stock first.
    """
    # 1. Query Variants directly
    # We use select_related('product') to avoid N+1 queries when fetching names
    low_variants = (
        models.ProductVariant.objects
        .filter(stock__lte=20,is_active=True)
        .select_related('product') 
        .order_by('stock')
    )

    # 2. Serialize manually for the chart
    # We combine Product Name + Volume so the admin knows exactly which item it is.
    data = []
    for v in low_variants:
        full_name = f"{v.product.name} ({v.volume})"
        
        data.append({
            "id": v.id,
            "name": full_name, # "Dior Sauvage (100ml)"
            "stock": v.stock
        })
        
    return Response({"variants": data}, status=status.HTTP_200_OK)

# ---------------------------------------------------------
# 2. TOP SELLING PRODUCTS
# ---------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_top_sales_chart_info(request):
    """
    Returns top selling variants (Product + Volume).
    """
    top_styles = (
        models.ProductVariant.objects
        .filter(orderitem__order__status='delivered') # Only delivered orders
        
        # 1. GROUP BY Product Name and Volume
        # This groups "Dior Sauvage 100ml" together
        .values('product__name', 'volume') 
        
        # 2. Sum the quantity for that group
        .annotate(total_sold=Sum('orderitem__quantity'))
        
        # 3. Sort by highest sales
        .order_by('-total_sold')[:16]
    )

    return Response({"topSelling": top_styles}, status=status.HTTP_200_OK)

# ---------------------------------------------------------
# 3. SALES & ORDERS CHART (Last 6 Months)
# ---------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_sales_orders_chart(request):
    try:
        # 1. Date Calculation
        today = timezone.now().date()
        six_months_ago = today - datetime.timedelta(days=180)
        
        # 2. Database Query
        sales_data = (
            models.Order.objects
            .filter(created_at__gte=six_months_ago)
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(
                total_orders=Count('id', distinct=True),
                # FIX: Explicitly set output_field=DecimalField()
                total_sales=Coalesce(
                    Sum(
                        F('items__quantity') * F('items__price'), 
                        output_field=DecimalField()
                    ),
                    Value(0, output_field=DecimalField())
                )
            )
            .order_by('month')
        )

        # 3. Create Lookup Dictionary
        sales_dict = {}
        for entry in sales_data:
            month_val = entry['month']
            
            # Safe String/Date handling
            if isinstance(month_val, str):
                key = month_val[:7] 
            elif isinstance(month_val, datetime.date):
                key = month_val.strftime('%Y-%m')
            else:
                continue 

            sales_dict[key] = {
                "orders": entry['total_orders'],
                "sales": entry['total_sales']
            }

        # 4. Fill Empty Months
        final_data = []
        for i in range(5, -1, -1):
            target_year = today.year
            target_month = today.month - i
            
            while target_month <= 0:
                target_month += 12
                target_year -= 1
                
            target_date = datetime.date(target_year, target_month, 1)
            key = target_date.strftime('%Y-%m')     
            display_name = target_date.strftime('%B') 

            stats = sales_dict.get(key, {"orders": 0, "sales": 0})

            final_data.append({
                "name": display_name,
                "orders": stats['orders'],
                "sales": stats['sales']
            })

        return Response(final_data, status=status.HTTP_200_OK)

    except Exception as e:
        # Print error to console for debugging
        print(f"Error in chart: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    

########## GOOGLE #############

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID

User = get_user_model() # <--- 2. Load your custom model

@api_view(['POST'])
@permission_classes([AllowAny]) 
def google_login(request):
    token = request.data.get('credential')
    
    if not token:
        return Response({"error": _("No token provided")}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Verify token with Google
        idinfo = id_token.verify_oauth2_token(
            token, 
            google_requests.Request(), 
            GOOGLE_CLIENT_ID
        )

        email = idinfo['email']
        first_name = idinfo.get('given_name', '')
        last_name = idinfo.get('family_name', '')
        
        # Combine into full_name as expected by the rest of the application
        full_name = f"{first_name} {last_name}".strip()
        if not full_name:
            full_name = email.split('@')[0]  # Fallback just in case

        # Get or Create the user (No username needed!)
        user, created = User.objects.get_or_create(email=email, defaults={
            'first_name': first_name,
            'last_name': last_name,
            'full_name': full_name,
        })

        if created:
            user.set_unusable_password()
            user.save()
        elif not user.full_name:
            # Fix existing users who logged in before we started saving full_name
            user.full_name = full_name
            user.save()

        # Generate JWT Tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': {
                'id': user.id,
                'email': user.email,
                'full_name': user.full_name,
            },
            'is_new_user': created
        }, status=status.HTTP_200_OK)

    except ValueError:
        return Response({"error": _("Invalid Google token")}, status=status.HTTP_400_BAD_REQUEST)

# --- BANNERS API ---
@api_view(['GET'])
@permission_classes([AllowAny])
def get_active_banners(request):
    """Public endpoint to get active banners for the storefront carousel."""
    banners = models.Banner.objects.filter(is_active=True)
    serializer = serializers.BannerSerializer(banners, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def manage_banners(request):
    """Admin dashboard endpoint to list all banners or create a new one."""
    if request.method == 'GET':
        banners = models.Banner.objects.all()
        serializer = serializers.DashboardBannerSerializer(banners, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    elif request.method == 'POST':
        # Handles text fields. For image uploads, parser_classes might be needed or handled via separate endpoint like variants.
        serializer = serializers.DashboardBannerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def manage_banner_detail(request, pk):
    """Admin dashboard endpoint to update, delete, or fetch a particular banner."""
    try:
        banner = models.Banner.objects.get(id=pk)
    except models.Banner.DoesNotExist:
        return Response({"error": _("Banner not found.")}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = serializers.DashboardBannerSerializer(banner)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    elif request.method == 'PATCH':
        serializer = serializers.DashboardBannerSerializer(banner, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    elif request.method == 'DELETE':
        banner.delete()
        return Response({'message': _('Banner deleted successfully.')}, status=status.HTTP_200_OK)

# --- SITE SETTINGS API ---
@api_view(['GET'])
@permission_classes([AllowAny])
@cache_page(60 * 15)
def get_site_settings(request):
    """Public endpoint to fetch all global site configurations like the top announcement bar."""
    settings_obj = models.SiteSettings.load()
    serializer = serializers.SiteSettingsSerializer(settings_obj)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def manage_site_settings(request):
    """Admin endpoint to view or update site settings."""
    settings_obj = models.SiteSettings.load()

    if request.method == 'GET':
        serializer = serializers.DashboardSiteSettingsSerializer(settings_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    elif request.method == 'PATCH':
        serializer = serializers.DashboardSiteSettingsSerializer(settings_obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- GOVERNORATE SHIPPING APIs ---

@api_view(['GET'])
@permission_classes([AllowAny])
def get_governorates(request):
    """Public endpoint for the checkout dropdown. Returns active governorates with their fees."""
    governorates = models.Governorate.objects.filter(is_active=True).order_by('name')
    serializer = serializers.GovernorateSerializer(governorates, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def manage_governorates(request):
    """Admin dashboard: list all governorates or create a new one."""
    if request.method == 'GET':
        show_all = request.query_params.get('all') == 'true' and request.user.is_staff
        if show_all:
            governorates = models.Governorate.objects.all().order_by('name')
            serializer = serializers.DashboardGovernorateSerializer(governorates, many=True)
        else:
            governorates = models.Governorate.objects.filter(is_active=True).order_by('name')
            serializer = serializers.GovernorateSerializer(governorates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        if not request.user.is_staff:
            return Response({"error": _("You can't perform this action")}, status=status.HTTP_403_FORBIDDEN)
        serializer = serializers.DashboardGovernorateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def manage_governorate_detail(request, pk):
    """Admin endpoint to edit or soft-delete a governorate."""
    try:
        governorate = models.Governorate.objects.get(id=pk)
    except models.Governorate.DoesNotExist:
        return Response({"error": _("Governorate not found.")}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PATCH':
        serializer = serializers.DashboardGovernorateSerializer(governorate, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": _("Governorate updated"), "data": serializer.data})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        is_hard_delete = request.query_params.get('hard') == 'true'

        if is_hard_delete:
            if models.Order.objects.filter(governorate=governorate).exists():
                return Response(
                    {"error": _("Cannot delete this governorate because it is referenced by existing orders. Please deactivate it instead.")},
                    status=status.HTTP_400_BAD_REQUEST
                )
            governorate.delete()
            return Response({"message": _("Governorate permanently deleted.")}, status=status.HTTP_200_OK)
        else:
            governorate.is_active = False
            governorate.save()
            return Response({"message": _("Governorate deactivated successfully.")}, status=status.HTTP_200_OK)

from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser
from base.services import DashboardService

class AdminDashboardAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        service = DashboardService()
        data = service.get_dashboard_analytics()
        return Response(data)

@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_admin_notifications(request):
    notifications = models.AdminNotification.objects.all()[:20]
    data = []
    for n in notifications:
        data.append({
            "id": n.id,
            "message": n.message,
            "is_read": n.is_read,
            "created_at": n.created_at
        })
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAdminUser])
def mark_notifications_read(request, pk=None):
    if pk:
        models.AdminNotification.objects.filter(pk=pk, is_read=False).update(is_read=True)
        return Response({"message": _("Notification marked as read")})
    else:
        models.AdminNotification.objects.filter(is_read=False).update(is_read=True)
        return Response({"message": _("All notifications marked as read")})

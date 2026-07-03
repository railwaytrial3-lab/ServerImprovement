
from django.db import models
import uuid
from cloudinary.models import CloudinaryField
from dirtyfields import DirtyFieldsMixin
from django.db.models import Avg
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import AbstractUser, BaseUserManager

class UserManager(BaseUserManager):
    def create_user(self, email, full_name, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, full_name, password, **extra_fields)

class User(AbstractUser):
    username = None  # Removes username field
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=100,null=True)

    # LINK THE NEW MANAGER HERE
    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        return self.full_name or self.email
    

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Governorate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('50.00'))
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Banner(models.Model):
    title = models.CharField(max_length=200)
    desktop_image = CloudinaryField("banners/", null=True)
    mobile_image = CloudinaryField("banners/mobile/", null=True, blank=True)
    link = models.URLField(max_length=500, blank=True, default="")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0, help_text="Order in which banner appears (lower numbers first)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-created_at']
        indexes = [
            models.Index(fields=['order', '-created_at']),
        ]

    def __str__(self):
        return self.title

class SiteSettings(models.Model):
    # This ensures there's only ever one row in the table
    # We will enforce this in the save method
    
    # --- Top Announcement Bar ---
    announcement_text = models.CharField(max_length=255, blank=True, default="", help_text="e.g. Free shipping for orders over $2000")
    announcement_link = models.URLField(max_length=500, blank=True, default="", help_text="Optional link when clicking the top bar")
    is_announcement_active = models.BooleanField(default=True)
    
    # --- Optional future additions ---
    # store_contact_email = models.EmailField(blank=True, null=True)
    # facebook_link = models.URLField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Site Settings"

    def save(self, *args, **kwargs):
        # Prevent creating a second row. Always update ID=1.
        self.pk = 1
        super(SiteSettings, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        # Automatically creates the first row if it doesn't exist yet
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Global Site Settings"


###################
class Product(models.Model):
    # Core Identity
    name = models.CharField(max_length=255)
    categories = models.ManyToManyField(Category, blank=True, related_name='products')
    description = models.TextField()
    
    # Perfume Specifics
    fragrance_family = models.CharField(max_length=255, blank=True, default="")
    concentration = models.CharField(max_length=255, blank=True, default="")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    is_bestseller = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    # Relationship
    product = models.ForeignKey(Product, related_name='variants', on_delete=models.CASCADE)
    
    # Specifics
    volume = models.CharField(max_length=50, default="100ml") # e.g., "50ml", "100ml"

    is_active = models.BooleanField(default=True)
    
    # Commerce
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        verbose_name="Current Price (Selling Price)"
    )
    compare_at_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        null=True, 
        blank=True,
        verbose_name="Original Price (MSRP)"
    )

    # ... stock fields ...
    stock = models.PositiveIntegerField(default=0)
    low_stock_notified = models.BooleanField(default=False, help_text="True if a low stock alert has already been sent.")


    @property
    def is_on_sale(self):
        """Returns True if the item is discounted."""
        if self.compare_at_price and self.compare_at_price > self.price:
            return True
        return False

    @property
    def discount_percentage(self):
        """Calculates the % off for badges (e.g., '25% OFF')."""
        if self.is_on_sale:
            discount = ((self.compare_at_price - self.price) / self.compare_at_price) * 100
            return round(discount)
        return 0

    @property
    def savings_amount(self):
        """Returns the actual money saved (e.g., '$20.00')."""
        if self.is_on_sale:
            return self.compare_at_price - self.price
        return 0
    
    @property
    def average_rating_value(self):
        return self.product.reviews.aggregate(avg=Avg("rating"))["avg"] or 0
 
    def __str__(self):
        return f"{self.product.name} - {self.volume}"
    
    class Meta:
        unique_together = ('product', 'volume')

    def save(self, *args, **kwargs):
        # Auto-reset the notification flag if stock is manually replenished above threshold
        if self.stock > 5 and self.low_stock_notified:
            self.low_stock_notified = False
        super().save(*args, **kwargs)


class ProductImage(models.Model):
    variant = models.ForeignKey(ProductVariant, related_name='images', on_delete=models.CASCADE)
    img = CloudinaryField("products/",null=True)
    is_thumbnail = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-is_thumbnail', 'id']
        
    def save(self, *args, **kwargs):
        if self.is_thumbnail:
            ProductImage.objects.filter(variant=self.variant).exclude(pk=self.pk).update(is_thumbnail=False)
        super().save(*args, **kwargs)
    
###################


class AdminNotification(models.Model):
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{'Read' if self.is_read else 'Unread'}: {self.message}"

class Review(models.Model):
    customer = models.ForeignKey(User,on_delete=models.CASCADE)
    product = models.ForeignKey(Product,on_delete=models.CASCADE,related_name='reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])  #1–5 stars
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        unique_together = ("product", "customer")  # one review per customer per product
        ordering = ["-created_at"]

    def __str__(self):
        return self.product.name
    

class WishList(models.Model):
    customer = models.ForeignKey(User,on_delete=models.CASCADE,related_name='wishlist')
    products = models.ManyToManyField(Product,related_name='wishlists',blank=True)

    def __str__(self):
        return self.customer.full_name or self.customer.email




class Order(DirtyFieldsMixin,models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(User,on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Biling details
    full_name = models.CharField(max_length=200)
    full_address = models.CharField(max_length=300)
    order_notes = models.TextField(blank=True,null=True, default="")
    phone_number = models.CharField(max_length=25)
    guest_email = models.EmailField(blank=True, null=True)
    device_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    country = models.CharField(max_length=100, default="Egypt")
    governorate = models.ForeignKey(Governorate, on_delete=models.SET_NULL, null=True, blank=True)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    @property
    def total_price(self):
        items_total = sum(item.quantity * item.price for item in self.items.all())
        return items_total + self.shipping_fee
    
    STATUS_CHOICES = [
    ("pending", "Pending"),
    ("awaiting_payment", "Awaiting Online Payment"),
    ("paid", "Paid"),
    ("shipped", "Shipped"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
    ("refunded", "Refunded"),
]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
 
    def __str__(self):
        return str(self.id)
    
    class Meta:
        ordering = ['-created_at']



class OrderItem(models.Model):
    order = models.ForeignKey(Order,on_delete=models.CASCADE,related_name='items')
    variant = models.ForeignKey(ProductVariant,on_delete=models.SET_NULL, null=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=8,decimal_places=2,blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    @property
    def subtotal(self): # for each item not whole order
        return self.quantity * self.price
    
    def save(self,*args,**kwargs):
        if self.variant:
            self.price = self.variant.price
        super().save(*args,**kwargs)

    def __str__(self):
        # Check if the relationship actually exists before accessing .product
        if self.variant: # (Change 'variant' to whatever your ForeignKey is named)
            return f"{self.variant.product.name} - {self.quantity}"
        
        # Fallback string if the original product was deleted
        return f"Unknown/Deleted Product - {self.quantity}"     

    class Meta:
        ordering = ['-created_at']

class Payment(models.Model):
    customer = models.ForeignKey(User,on_delete=models.CASCADE,related_name='payments', null=True, blank=True)
    order = models.OneToOneField(Order,on_delete=models.CASCADE,related_name='payment')
    amount = models.DecimalField(decimal_places=2,max_digits=10)

    METHOD_CHOICES = [
        ("credit_card","Credit Card"),
        ("debit_card","Debit Card"),
        ("cash","Cash"),
        ("cod","Cash on Delivery"),
        ("paypal","PayPal"),
        ("bank_transfer","Bank Transfer"),
        ("stripe","Stripe"),
        ("paymob", "Paymob"),
    ]

    method = models.CharField(max_length=50,choices=METHOD_CHOICES)
    created_at = models.DateTimeField(auto_now_add = True)
    updated = models.DateTimeField(auto_now = True)
    transaction_id = models.CharField(max_length=100, null=True, unique=True)

    def __str__(self):
        return (self.customer.full_name or self.customer.email) if self.customer else "Guest Payment"




class Cart(models.Model):
    customer = models.ForeignKey(User,on_delete=models.CASCADE,null=True,blank=True)

    device_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(customer__isnull=False) | models.Q(device_id__isnull=False),
                name='cart_must_have_customer_or_device'
            )
        ]

    @property
    def total_price(self):
        return sum(item.subtotal for item in self.items.all())

    def __str__(self):
        if self.customer:
            return self.customer.full_name or self.customer.email
        return "Guest Cart"




class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(ProductVariant,on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=8,decimal_places=2,blank=True)

    @property
    def subtotal(self): # for each item not whole cart
        return self.quantity * self.price
    
    def save(self,*args,**kwargs):
        self.price = self.variant.price
        
        super().save(*args,**kwargs)

    def __str__(self):
        return self.variant.product.name
    
    class Meta:
        ordering = ['id']


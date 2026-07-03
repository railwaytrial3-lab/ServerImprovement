from django.contrib import admin
from . import models
from modeltranslation.admin import TranslationAdmin

class ProductImageInline(admin.TabularInline):
    model = models.ProductImage
    extra = 1
    fields = ('img', 'is_thumbnail')

class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('product', 'volume', 'price', 'stock')
    inlines = [ProductImageInline]

# Register your models here.
admin.site.register(models.User)

@admin.register(models.Category)
class CategoryAdmin(TranslationAdmin):
    pass

admin.site.register(models.Order)
admin.site.register(models.OrderItem)
admin.site.register(models.Payment)
admin.site.register(models.Cart)
admin.site.register(models.CartItem)
admin.site.register(models.AdminNotification)
admin.site.register(models.Governorate)

@admin.register(models.Product)
class ProductAdmin(TranslationAdmin):
    pass

admin.site.register(models.ProductVariant, ProductVariantAdmin)
admin.site.register(models.Review)
admin.site.register(models.WishList)
admin.site.register(models.ProductImage)

@admin.register(models.Banner)
class BannerAdmin(TranslationAdmin):
    pass

@admin.register(models.SiteSettings)
class SiteSettingsAdmin(TranslationAdmin):
    pass

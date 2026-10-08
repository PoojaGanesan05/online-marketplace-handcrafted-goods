from django.contrib import admin

from .models import Cart, Notification, Order, Product, Profile, Review, Wishlist


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role')
    list_filter = ('role',)
    search_fields = ('user__username',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'seller', 'price', 'created_at')
    search_fields = ('name', 'seller__username')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'buyer', 'total_amount', 'payment_method', 'confirmed', 'ordered_at')
    list_filter = ('confirmed', 'payment_method')
    search_fields = ('product__name', 'buyer__username')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'buyer', 'rating', 'ordered_at')
    list_filter = ('rating',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'message', 'is_read', 'created_at')
    list_filter = ('is_read',)


admin.site.register(Wishlist)
admin.site.register(Cart)

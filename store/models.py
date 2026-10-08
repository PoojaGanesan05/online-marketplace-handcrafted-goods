from django.db import models
from django.contrib.auth.models import User

# Profile model
class Profile(models.Model):
    ROLE_CHOICES = (
        ('buyer', 'Buyer'),
        ('seller', 'Seller'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"

# Automatically create a Profile when a new User is created
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

# Product model
class Product(models.Model):
    seller = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    image = models.ImageField(upload_to='products/')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class OrderQuerySet(models.QuerySet):
    """An order is a *draft* until the buyer picks a payment method, then it is *placed*.
    Only placed orders are shown to sellers and in the buyer's order history."""

    def placed(self):
        return self.exclude(models.Q(payment_method__isnull=True) | models.Q(payment_method=''))

    def drafts(self):
        return self.filter(models.Q(payment_method__isnull=True) | models.Q(payment_method=''))


# Order model
class Order(models.Model):
    PAYMENT_METHODS = (
        ('gpay', 'GPay'),
        ('phonepe', 'PhonePe'),
        ('cod', 'Cash on Delivery'),
    )

    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='buyer_orders')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    confirmed = models.BooleanField(default=False)
    delivery_address = models.TextField(blank=True, null=True)
    mobile_number = models.CharField(max_length=15, blank=True, null=True)
    delivery_charge = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, blank=True, null=True)
    ordered_at = models.DateTimeField(auto_now_add=True)

    objects = OrderQuerySet.as_manager()

    @property
    def status(self):
        return 'Confirmed' if self.confirmed else 'Pending'

    def save(self, *args, **kwargs):
        # Automatically calculate total amount before saving
        if self.product and self.delivery_charge is not None:
            self.total_amount = self.product.price + self.delivery_charge
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} ordered by {self.buyer.username}"


# Review model
class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    buyer = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    rating = models.IntegerField(null=True, blank=True)  # Optional rating
    ordered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review by {self.buyer.username} on {self.product.name}"

# Wishlist model
class Wishlist(models.Model):
    buyer = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.buyer.username} - {self.product.name}"

# Cart model
class Cart(models.Model):
    buyer = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} in cart of {self.buyer.username}"

# Notification model
class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification to {self.user.username}"

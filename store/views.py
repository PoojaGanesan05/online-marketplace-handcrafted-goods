from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.db.models import Avg
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CheckoutForm, PaymentForm, ProductForm, ReviewForm, SignupForm
from .models import Profile, Product, Order, Review, Wishlist, Cart, Notification

DELIVERY_CHARGE = Decimal('50.00')
MAX_FILTER_PRICE = Decimal('99999999.99')

# Session keys used to follow one order through review -> payment -> confirmation
CHECKOUT_SESSION_KEY = 'checkout_order_id'
LAST_ORDER_SESSION_KEY = 'last_order_id'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_role(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile.role


def _dashboard_for(role):
    """Name of the landing page for a role (users without a role must choose one first)."""
    if role == 'seller':
        return 'seller_dashboard'
    if role == 'buyer':
        return 'buyer_dashboard'
    return 'role_selection'


def role_required(role):
    """Login + role guard. Wrong role -> sent to their own dashboard; no role -> role selection."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            current = _get_role(request.user)
            if current != role:
                if current is None:
                    messages.info(request, 'Please choose how you want to use the marketplace.')
                else:
                    messages.warning(request, f'That page is only available to {role}s.')
                return redirect(_dashboard_for(current))
            return view_func(request, *args, **kwargs)
        return login_required(wrapper)
    return decorator


def _parse_price(raw):
    """Return (Decimal or None, was_invalid) for a price typed into a filter box."""
    raw = (raw or '').strip()
    if not raw:
        return None, False
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None, True
    if not value.is_finite() or not (0 <= value <= MAX_FILTER_PRICE):
        return None, True
    return value, False


# ---------------------------------------------------------------------------
# Home & authentication
# ---------------------------------------------------------------------------
def home(request):
    dashboard_url = None
    if request.user.is_authenticated:
        dashboard_url = reverse(_dashboard_for(_get_role(request.user)))
    return render(request, 'store/home.html', {'dashboard_url': dashboard_url})


def signup_view(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            try:
                user = User.objects.create_user(
                    username=form.cleaned_data['username'],
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password'],
                )
            except IntegrityError:  # two people registering the same name at once
                form.add_error('username', 'This username is already taken.')
            else:
                login(request, user)
                messages.success(request, 'Account created. Welcome!')
                return redirect('role_selection')
    else:
        form = SignupForm()
    return render(request, 'store/signup.html', {'form': form})


def login_view(request):
    next_url = request.POST.get('next') or request.GET.get('next', '')
    if request.method == "POST":
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            if next_url and url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect(_dashboard_for(_get_role(user)))
        messages.error(request, 'Invalid credentials')
    return render(request, 'store/login.html', {'next': next_url})


def logout_view(request):
    logout(request)
    return redirect('home')


@login_required
def role_selection(request):
    if request.method == "POST":
        role = request.POST.get('role')
        if role not in dict(Profile.ROLE_CHOICES):
            messages.error(request, 'Please choose Buyer or Seller.')
            return redirect('role_selection')
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.role = role
        profile.save()
        return redirect(_dashboard_for(role))
    return render(request, 'store/role_selection.html')


# ---------------------------------------------------------------------------
# Seller
# ---------------------------------------------------------------------------
@role_required('seller')
def seller_dashboard(request):
    products = Product.objects.filter(seller=request.user).order_by('-created_at')
    orders = (Order.objects.placed().filter(product__seller=request.user)
              .select_related('buyer', 'product').order_by('-ordered_at'))
    reviews = (Review.objects.filter(product__seller=request.user)
               .select_related('buyer', 'product').order_by('-ordered_at'))

    if request.method == 'POST' and 'upload_product' in request.POST:
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.seller = request.user
            product.save()
            messages.success(request, "Product uploaded successfully.")
            return redirect('seller_dashboard')
        messages.error(request, "Could not upload the product. Please fix the errors below.")
    else:
        form = ProductForm()

    return render(request, 'store/seller_dashboard.html', {
        'form': form,
        'products': products,
        'orders': orders,
        'reviews': reviews,
    })


@role_required('seller')
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id, seller=request.user)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, "Product updated successfully.")
            return redirect('seller_dashboard')
        messages.error(request, "Could not save the changes. Please fix the errors below.")
    return render(request, 'store/edit_product.html', {'form': form, 'product': product})


@require_POST
@role_required('seller')
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id, seller=request.user)
    product.delete()
    messages.success(request, "Product deleted successfully.")
    return redirect('seller_dashboard')


@require_POST
@role_required('seller')
def confirm_order(request, order_id):
    order = get_object_or_404(Order.objects.placed(), id=order_id, product__seller=request.user)
    if order.confirmed:
        messages.info(request, f"Order for {order.product.name} was already confirmed.")
        return redirect('seller_dashboard')
    order.confirmed = True
    # update_fields keeps the stored total unchanged even if the product price was edited since
    order.save(update_fields=['confirmed'])
    Notification.objects.create(user=order.buyer, message=f"Your order for '{order.product.name}' was confirmed.")
    messages.success(request, f"Order for {order.product.name} confirmed.")
    return redirect('seller_dashboard')


@require_POST
@role_required('seller')
def reject_order(request, order_id):
    order = get_object_or_404(Order.objects.placed(), id=order_id, product__seller=request.user)
    if order.confirmed:
        messages.error(request, "A confirmed order can no longer be rejected.")
        return redirect('seller_dashboard')
    Notification.objects.create(user=order.buyer, message=f"Your order for '{order.product.name}' was rejected.")
    order.delete()
    messages.warning(request, f"Order for {order.product.name} was rejected.")
    return redirect('seller_dashboard')


# ---------------------------------------------------------------------------
# Buyer dashboard
# ---------------------------------------------------------------------------
@role_required('buyer')
def buyer_dashboard(request):
    products = Product.objects.all().order_by('-created_at')
    query = (request.GET.get('q') or request.GET.get('query') or '').strip()
    min_price, bad_min = _parse_price(request.GET.get('min_price'))
    max_price, bad_max = _parse_price(request.GET.get('max_price'))

    if bad_min or bad_max:
        messages.warning(request, 'An invalid price filter was ignored.')
    if query:
        products = products.filter(name__icontains=query)
    if min_price is not None:
        products = products.filter(price__gte=min_price)
    if max_price is not None:
        products = products.filter(price__lte=max_price)

    return render(request, 'store/buyer_dashboard.html', {
        'products': products,
        'query': query,
        'min_price': request.GET.get('min_price', '') if not bad_min else '',
        'max_price': request.GET.get('max_price', '') if not bad_max else '',
        'filters_active': bool(query or min_price is not None or max_price is not None),
        'wishlist_items': Wishlist.objects.filter(buyer=request.user),
        'cart_items': Cart.objects.filter(buyer=request.user),
        'unread_count': Notification.objects.filter(user=request.user, is_read=False).count(),
    })


# ---------------------------------------------------------------------------
# Order process: place -> review (address) -> payment -> confirmation
# ---------------------------------------------------------------------------
def _start_checkout(request, product):
    """Return this buyer's unfinished (draft) order for the product, creating it if needed,
    and remember it in the session so the next steps act on the right order."""
    draft = (Order.objects.drafts().filter(buyer=request.user, product=product).order_by('-ordered_at').first()
             or Order.objects.create(buyer=request.user, product=product))
    request.session[CHECKOUT_SESSION_KEY] = draft.id
    return draft


def _own_product_redirect(request, product):
    if product.seller_id == request.user.id:
        messages.error(request, "You can't order your own product.")
        return redirect('buyer_dashboard')
    return None


@role_required('buyer')
def place_order(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    blocked = _own_product_redirect(request, product)
    if blocked:
        return blocked
    _start_checkout(request, product)
    return redirect('review_order', product_id=product.id)


@role_required('buyer')
def review_order(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    blocked = _own_product_redirect(request, product)
    if blocked:
        return blocked
    draft = _start_checkout(request, product)

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            draft.delivery_address = form.cleaned_data['address']
            draft.mobile_number = form.cleaned_data['mobile']
            draft.delivery_charge = DELIVERY_CHARGE
            draft.save()  # total_amount = price + delivery_charge is computed in Order.save()
            return redirect('payment_selection')
    else:
        form = CheckoutForm(initial={
            'address': draft.delivery_address or '',
            'mobile': draft.mobile_number or '',
        })

    return render(request, 'store/review_order.html', {
        'product': product,
        'delivery_charge': DELIVERY_CHARGE,
        'total': product.price + DELIVERY_CHARGE,
        'form': form,
    })


@role_required('buyer')
def payment_selection(request):
    order = (Order.objects.drafts()
             .filter(id=request.session.get(CHECKOUT_SESSION_KEY), buyer=request.user)
             .select_related('product').first())
    if order is None:
        messages.info(request, 'Choose a product to order first.')
        return redirect('buyer_dashboard')
    if not order.delivery_address or not order.mobile_number:
        messages.info(request, 'Please enter your delivery details first.')
        return redirect('review_order', product_id=order.product_id)

    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            order.payment_method = form.cleaned_data['payment_method']
            order.save()
            Cart.objects.filter(buyer=request.user, product=order.product).delete()  # bought -> leaves the cart
            request.session.pop(CHECKOUT_SESSION_KEY, None)
            request.session[LAST_ORDER_SESSION_KEY] = order.id
            return redirect('confirm_order_page')
        messages.error(request, 'Please choose a payment method.')
    else:
        form = PaymentForm()
    return render(request, 'store/payment_selection.html', {'order': order, 'form': form})


@role_required('buyer')
def confirm_order_page(request):
    order = (Order.objects.placed()
             .filter(id=request.session.get(LAST_ORDER_SESSION_KEY), buyer=request.user)
             .select_related('product').first())
    if order is None:
        messages.info(request, 'You have no recent order to confirm.')
        return redirect('order_history')
    return render(request, 'store/confirm_order_page.html', {'order': order})


@role_required('buyer')
def order_history(request):
    orders = (Order.objects.placed().filter(buyer=request.user)
              .select_related('product').order_by('-ordered_at'))
    return render(request, 'store/order_history.html', {'orders': orders})


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
@require_POST
@role_required('buyer')
def add_to_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if Wishlist.objects.filter(buyer=request.user, product=product).exists():
        messages.info(request, f"'{product.name}' is already in your wishlist.")
    else:
        Wishlist.objects.create(buyer=request.user, product=product)
        messages.success(request, f"Added '{product.name}' to your wishlist.")
    return redirect('buyer_dashboard')


@role_required('buyer')
def view_wishlist(request):
    wishlist_items = Wishlist.objects.filter(buyer=request.user).select_related('product').order_by('-id')
    return render(request, 'store/wishlist.html', {'wishlist_items': wishlist_items})


@require_POST
@role_required('buyer')
def remove_from_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    Wishlist.objects.filter(buyer=request.user, product=product).delete()
    messages.success(request, f"Removed '{product.name}' from your wishlist.")
    return redirect('view_wishlist')


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
@require_POST
@role_required('buyer')
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if Cart.objects.filter(buyer=request.user, product=product).exists():
        messages.info(request, f"'{product.name}' is already in your cart.")
    else:
        Cart.objects.create(buyer=request.user, product=product)
        messages.success(request, f"Added '{product.name}' to your cart.")
    return redirect('buyer_dashboard')


@role_required('buyer')
def view_cart(request):
    cart_items = Cart.objects.filter(buyer=request.user).select_related('product').order_by('-added_at')
    return render(request, 'store/cart.html', {'cart_items': cart_items})


@require_POST
@role_required('buyer')
def remove_from_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    Cart.objects.filter(buyer=request.user, product=product).delete()
    messages.success(request, f"Removed '{product.name}' from your cart.")
    return redirect('view_cart')


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
def _reviews_page(request, product, form):
    reviews = Review.objects.filter(product=product).select_related('buyer').order_by('-ordered_at')
    average = reviews.aggregate(avg=Avg('rating'))['avg']
    return render(request, 'store/reviews.html', {
        'product': product,
        'reviews': reviews,
        'form': form,
        'average_rating': round(average, 1) if average is not None else None,
    })


@role_required('buyer')
def view_reviews(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    return _reviews_page(request, product, ReviewForm())


@role_required('buyer')
def submit_review(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method != 'POST':
        return redirect('view_reviews', product_id=product.id)

    form = ReviewForm(request.POST)
    if form.is_valid():
        Review.objects.create(
            product=product,
            buyer=request.user,
            comment=form.cleaned_data['comment'],
            rating=form.cleaned_data['rating'],
        )
        messages.success(request, "Review submitted!")
        return redirect('view_reviews', product_id=product.id)
    messages.error(request, "Your review could not be saved. Please fix the errors below.")
    return _reviews_page(request, product, form)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@role_required('buyer')
def view_notifications(request):
    notifications = list(Notification.objects.filter(user=request.user).order_by('-created_at'))
    unread_ids = [n.id for n in notifications if not n.is_read]
    response = render(request, 'store/notifications.html', {'notifications': notifications})
    # Marked as read only after the page was rendered, so this visit still shows which ones were new.
    Notification.objects.filter(id__in=unread_ids).update(is_read=True)
    return response

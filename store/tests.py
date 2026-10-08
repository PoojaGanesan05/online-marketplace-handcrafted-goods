import io
import re
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image

from .models import Cart, Notification, Order, Product, Review, Wishlist

TEMP_MEDIA = tempfile.mkdtemp()
PASSWORD = 'Str0ng-pass-123'


def make_image(name='p.png'):
    buf = io.BytesIO()
    Image.new('RGB', (10, 10), (200, 50, 50)).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=TEMP_MEDIA,
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])  # fast hashing, tests only
class MarketTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def make_user(self, username, role=None):
        user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
        user.profile.role = role
        user.profile.save()
        return user

    def as_user(self, user):
        client = Client()
        client.login(username=user.username, password=PASSWORD)
        return client

    def make_product(self, seller, name='Clay Pot', price='500'):
        return Product.objects.create(seller=seller, name=name, image='products/x.png', price=Decimal(price))

    def setUp(self):
        self.seller = self.make_user('seller', 'seller')
        self.other_seller = self.make_user('seller2', 'seller')
        self.buyer = self.make_user('buyer', 'buyer')
        self.product = self.make_product(self.seller)
        self.sc = self.as_user(self.seller)
        self.bc = self.as_user(self.buyer)

    def place_order(self, client=None, mobile='9876543210', method='cod'):
        client = client or self.bc
        client.get(f'/order/{self.product.id}/')
        client.post(f'/review-order/{self.product.id}/', {'address': '12 Main Street, Chennai', 'mobile': mobile})
        client.post('/payment/', {'payment_method': method})
        return Order.objects.placed().latest('ordered_at')

    def msgs(self, response):
        return [str(m) for m in response.context['messages']]


class PublicAndAuthTests(MarketTestCase):
    def test_public_pages_render(self):
        for url in ('/', '/login/', '/signup/'):
            self.assertEqual(Client().get(url).status_code, 200, url)

    def test_home_offers_dashboard_when_logged_in(self):
        self.assertContains(self.bc.get('/'), 'Go to Dashboard')
        self.assertContains(Client().get('/'), 'Sign Up')

    def test_signup_creates_user_logs_in_and_asks_for_role(self):
        c = Client()
        r = c.post('/signup/', {'username': 'newbie', 'email': 'n@example.com', 'password': PASSWORD})
        self.assertRedirects(r, '/select-role/')
        self.assertTrue(User.objects.filter(username='newbie').exists())

    def test_signup_errors_are_friendly(self):
        c = Client()
        dup = c.post('/signup/', {'username': 'BUYER', 'email': 'a@example.com', 'password': PASSWORD})
        self.assertContains(dup, 'already taken')
        weak = c.post('/signup/', {'username': 'weak', 'email': 'a@example.com', 'password': '1'})
        self.assertEqual(weak.status_code, 200)
        self.assertFalse(User.objects.filter(username='weak').exists())
        missing = c.post('/signup/', {'username': 'x'})
        self.assertEqual(missing.status_code, 200)
        badmail = c.post('/signup/', {'username': 'y', 'email': 'nope', 'password': PASSWORD})
        self.assertContains(badmail, 'valid email')

    def test_login_redirects_by_role(self):
        self.assertRedirects(Client().post('/login/', {'username': 'seller', 'password': PASSWORD}),
                             '/seller/dashboard/')
        self.assertRedirects(Client().post('/login/', {'username': 'buyer', 'password': PASSWORD}),
                             '/buyer/dashboard/')

    def test_login_without_role_goes_to_role_selection(self):
        self.make_user('norole')
        r = Client().post('/login/', {'username': 'norole', 'password': PASSWORD})
        self.assertRedirects(r, '/select-role/')

    def test_login_wrong_password(self):
        r = Client().post('/login/', {'username': 'buyer', 'password': 'bad'})
        self.assertContains(r, 'Invalid credentials')

    def test_next_is_honoured_only_for_local_urls(self):
        r = Client().post('/login/', {'username': 'buyer', 'password': PASSWORD, 'next': '/cart/'})
        self.assertRedirects(r, '/cart/')
        r = Client().post('/login/', {'username': 'buyer', 'password': PASSWORD, 'next': 'https://evil.example/'})
        self.assertRedirects(r, '/buyer/dashboard/')

    def test_logout(self):
        r = self.bc.get('/logout/')
        self.assertRedirects(r, '/')
        self.assertEqual(self.bc.get('/cart/').status_code, 302)

    def test_login_required_pages_bounce_to_login(self):
        for url in ('/cart/', '/wishlist/', '/orders/', '/seller/dashboard/', '/buyer/dashboard/', '/notifications/'):
            r = Client().get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn('/login/', r['Location'])


class RoleTests(MarketTestCase):
    def test_role_selection(self):
        user = self.make_user('rs')
        c = self.as_user(user)
        self.assertRedirects(c.post('/select-role/', {'role': 'seller'}), '/seller/dashboard/')
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.role, 'seller')

    def test_bogus_role_rejected(self):
        user = self.make_user('rs')
        c = self.as_user(user)
        c.post('/select-role/', {'role': 'admin'})
        user.profile.refresh_from_db()
        self.assertIsNone(user.profile.role)

    def test_wrong_role_is_redirected_to_own_dashboard(self):
        self.assertRedirects(self.bc.get('/seller/dashboard/'), '/buyer/dashboard/')
        self.assertRedirects(self.sc.get('/buyer/dashboard/'), '/seller/dashboard/')
        self.assertRedirects(self.sc.get('/cart/'), '/seller/dashboard/')

    def test_no_role_user_is_sent_to_role_selection(self):
        c = self.as_user(self.make_user('norole'))
        self.assertRedirects(c.get('/buyer/dashboard/'), '/select-role/')


class SellerProductTests(MarketTestCase):
    def test_dashboard_loads_with_empty_state(self):
        c = self.as_user(self.other_seller)
        r = c.get('/seller/dashboard/')
        self.assertContains(r, 'No products uploaded yet')
        self.assertContains(r, 'No orders placed yet')

    def test_upload_product(self):
        r = self.sc.post('/seller/dashboard/', {'upload_product': '1', 'name': ' Vase ', 'price': '300', 'image': make_image()})
        self.assertRedirects(r, '/seller/dashboard/')
        self.assertTrue(Product.objects.filter(name='Vase', seller=self.seller).exists())

    def test_invalid_uploads_show_errors_and_save_nothing(self):
        before = Product.objects.count()
        for data in ({'name': '', 'price': '5'}, {'name': 'A', 'price': 'abc', 'image': make_image()},
                     {'name': 'A', 'price': '-5', 'image': make_image()}, {'name': 'A', 'price': '0', 'image': make_image()},
                     {'name': 'A', 'price': '5', 'image': SimpleUploadedFile('x.png', b'notimage', 'image/png')}):
            r = self.sc.post('/seller/dashboard/', {'upload_product': '1', **data})
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'errorlist')
        self.assertEqual(Product.objects.count(), before)

    def test_buyer_cannot_upload(self):
        self.bc.post('/seller/dashboard/', {'upload_product': '1', 'name': 'Hack', 'price': '1', 'image': make_image()})
        self.assertFalse(Product.objects.filter(name='Hack').exists())

    def test_edit_product(self):
        self.assertEqual(self.sc.get(f'/product/edit/{self.product.id}/').status_code, 200)
        r = self.sc.post(f'/product/edit/{self.product.id}/', {'name': 'Clay Pot 2', 'price': '520'})
        self.assertRedirects(r, '/seller/dashboard/')
        self.product.refresh_from_db()
        self.assertEqual((self.product.name, self.product.price), ('Clay Pot 2', Decimal('520')))

    def test_edit_with_invalid_data_shows_errors(self):
        r = self.sc.post(f'/product/edit/{self.product.id}/', {'name': '', 'price': '-1'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'errorlist')

    def test_cannot_edit_or_delete_another_sellers_product(self):
        other = self.as_user(self.other_seller)
        self.assertEqual(other.get(f'/product/edit/{self.product.id}/').status_code, 404)
        self.assertEqual(other.post(f'/product/delete/{self.product.id}/').status_code, 404)
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())

    def test_delete_needs_post(self):
        self.assertEqual(self.sc.get(f'/product/delete/{self.product.id}/').status_code, 405)
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())
        self.assertRedirects(self.sc.post(f'/product/delete/{self.product.id}/'), '/seller/dashboard/')
        self.assertFalse(Product.objects.filter(id=self.product.id).exists())


class BuyerDashboardTests(MarketTestCase):
    def setUp(self):
        super().setUp()
        self.make_product(self.seller, 'Silk Scarf', '1500')

    def test_lists_all_products(self):
        r = self.bc.get('/buyer/dashboard/')
        self.assertContains(r, 'Clay Pot')
        self.assertContains(r, 'Silk Scarf')

    def test_search_box_field_q_filters(self):
        r = self.bc.get('/buyer/dashboard/?q=scarf')
        self.assertContains(r, 'Silk Scarf')
        self.assertNotContains(r, 'Clay Pot')

    def test_legacy_query_param_and_empty_state(self):
        self.assertContains(self.bc.get('/buyer/dashboard/?query=clay'), 'Clay Pot')
        self.assertContains(self.bc.get('/buyer/dashboard/?q=zzzz'), 'No products match your search')

    def test_price_filter(self):
        r = self.bc.get('/buyer/dashboard/?min_price=1000&max_price=2000')
        self.assertContains(r, 'Silk Scarf')
        self.assertNotContains(r, 'Clay Pot')

    def test_invalid_price_is_ignored_with_a_warning(self):
        for bad in ('abc', 'NaN', '-3', '1e999999'):
            r = self.bc.get('/buyer/dashboard/', {'min_price': bad})
            self.assertEqual(r.status_code, 200, bad)
            self.assertIn('An invalid price filter was ignored.', self.msgs(r))
            self.assertContains(r, 'Clay Pot')


class WishlistAndCartTests(MarketTestCase):
    def test_add_is_post_only_and_idempotent(self):
        self.assertEqual(self.bc.get(f'/wishlist/add/{self.product.id}/').status_code, 405)
        self.assertEqual(self.bc.get(f'/cart/add/{self.product.id}/').status_code, 405)
        for _ in range(2):
            self.bc.post(f'/wishlist/add/{self.product.id}/')
            self.bc.post(f'/cart/add/{self.product.id}/')
        self.assertEqual(Wishlist.objects.filter(buyer=self.buyer).count(), 1)
        self.assertEqual(Cart.objects.filter(buyer=self.buyer).count(), 1)

    def test_feedback_message_shown_on_dashboard(self):
        r = self.bc.post(f'/cart/add/{self.product.id}/', follow=True)
        self.assertContains(r, 'Added &#x27;Clay Pot&#x27; to your cart')

    def test_view_and_remove(self):
        self.bc.post(f'/wishlist/add/{self.product.id}/')
        self.bc.post(f'/cart/add/{self.product.id}/')
        self.assertContains(self.bc.get('/wishlist/'), 'Clay Pot')
        self.assertContains(self.bc.get('/cart/'), 'Clay Pot')
        self.assertEqual(self.bc.get(f'/cart/remove/{self.product.id}/').status_code, 405)
        self.assertRedirects(self.bc.post(f'/cart/remove/{self.product.id}/'), '/cart/')
        self.assertRedirects(self.bc.post(f'/wishlist/remove/{self.product.id}/'), '/wishlist/')
        self.assertContains(self.bc.get('/cart/'), 'Your cart is empty')
        self.assertContains(self.bc.get('/wishlist/'), 'Your wishlist is empty')

    def test_items_are_private_per_buyer(self):
        self.bc.post(f'/cart/add/{self.product.id}/')
        other = self.as_user(self.make_user('buyer2', 'buyer'))
        self.assertContains(other.get('/cart/'), 'Your cart is empty')

    def test_missing_product_is_404(self):
        self.assertEqual(self.bc.post('/cart/add/9999/').status_code, 404)


class CheckoutTests(MarketTestCase):
    def test_review_page_shows_delivery_and_total(self):
        r = self.bc.get(f'/order/{self.product.id}/', follow=True)
        self.assertContains(r, '₹50.00')
        self.assertContains(r, '₹550.00')

    def test_full_checkout(self):
        self.bc.post(f'/cart/add/{self.product.id}/')
        order = self.place_order(method='gpay')
        self.assertEqual(order.payment_method, 'gpay')
        self.assertEqual(order.total_amount, Decimal('550.00'))
        self.assertFalse(order.confirmed)
        self.assertEqual(Cart.objects.filter(buyer=self.buyer).count(), 0)
        r = self.bc.get('/confirm-order/')
        self.assertContains(r, 'Order Placed Successfully')
        self.assertContains(r, 'GPay')
        self.assertContains(self.bc.get('/orders/'), 'Clay Pot')

    def test_clicking_order_repeatedly_creates_a_single_draft(self):
        for _ in range(3):
            self.bc.get(f'/order/{self.product.id}/')
        self.assertEqual(Order.objects.filter(buyer=self.buyer).count(), 1)

    def test_checkout_details_are_validated(self):
        self.bc.get(f'/order/{self.product.id}/')
        for data in ({'address': 'short', 'mobile': '9876543210'}, {'address': '12 Main Street, Chennai', 'mobile': 'abc'},
                     {'address': '', 'mobile': ''}):
            r = self.bc.post(f'/review-order/{self.product.id}/', data)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'text-danger')

    def test_form_keeps_what_the_user_typed(self):
        self.bc.get(f'/order/{self.product.id}/')
        r = self.bc.post(f'/review-order/{self.product.id}/', {'address': '12 Main Street, Chennai', 'mobile': 'abc'})
        self.assertContains(r, '12 Main Street, Chennai')

    def test_invalid_payment_method_rejected(self):
        self.bc.get(f'/order/{self.product.id}/')
        self.bc.post(f'/review-order/{self.product.id}/', {'address': '12 Main Street, Chennai', 'mobile': '9876543210'})
        r = self.bc.post('/payment/', {'payment_method': 'bitcoin'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Order.objects.placed().count(), 0)

    def test_pages_without_an_order_do_not_crash(self):
        fresh = self.as_user(self.make_user('fresh', 'buyer'))
        self.assertRedirects(fresh.get('/payment/'), '/buyer/dashboard/')
        self.assertRedirects(fresh.post('/payment/', {'payment_method': 'cod'}), '/buyer/dashboard/')
        self.assertRedirects(fresh.get('/confirm-order/'), '/orders/')

    def test_payment_before_address_goes_back_to_review(self):
        self.bc.get(f'/order/{self.product.id}/')
        self.assertRedirects(self.bc.get('/payment/'), f'/review-order/{self.product.id}/')

    def test_abandoned_checkout_is_invisible_to_seller(self):
        self.bc.get(f'/order/{self.product.id}/')
        self.assertContains(self.sc.get('/seller/dashboard/'), 'No orders placed yet')
        self.assertContains(self.bc.get('/orders/'), "placed any orders")

    def test_two_products_do_not_get_mixed_up(self):
        second = self.make_product(self.seller, 'Vase', '300')
        self.bc.get(f'/order/{self.product.id}/')
        self.bc.get(f'/order/{second.id}/')
        self.bc.post(f'/review-order/{second.id}/', {'address': '12 Main Street, Chennai', 'mobile': '9876543210'})
        self.bc.post('/payment/', {'payment_method': 'cod'})
        self.assertEqual(Order.objects.placed().get().product, second)

    def test_cannot_order_own_product(self):
        self.sc.post('/select-role/', {'role': 'buyer'})
        r = self.sc.get(f'/order/{self.product.id}/')
        self.assertRedirects(r, '/buyer/dashboard/')
        self.assertEqual(Order.objects.count(), 0)

    def test_seller_cannot_use_buyer_checkout(self):
        self.assertRedirects(self.other_seller_client().get(f'/order/{self.product.id}/'), '/seller/dashboard/')

    def other_seller_client(self):
        return self.as_user(self.other_seller)


class SellerOrderTests(MarketTestCase):
    def test_seller_sees_order_and_confirms_it(self):
        order = self.place_order()
        page = self.sc.get('/seller/dashboard/')
        self.assertContains(page, 'buyer')
        self.assertContains(page, 'Cash on Delivery')
        self.assertContains(page, 'Pending')
        self.assertEqual(self.sc.get(f'/confirm-order/{order.id}/').status_code, 405)
        r = self.sc.post(f'/confirm-order/{order.id}/')
        self.assertRedirects(r, '/seller/dashboard/')
        order.refresh_from_db()
        self.assertTrue(order.confirmed)
        self.assertEqual(Notification.objects.filter(user=self.buyer).count(), 1)
        self.assertContains(self.sc.get('/seller/dashboard/'), 'Confirmed')

    def test_confirm_marks_order_and_notifies_buyer_once(self):
        order = self.place_order()
        self.sc.post(f'/confirm-order/{order.id}/')
        self.sc.post(f'/confirm-order/{order.id}/')
        self.assertEqual(Notification.objects.filter(user=self.buyer).count(), 1)

    def test_confirming_keeps_the_stored_total_even_if_price_changed(self):
        order = self.place_order()
        self.product.price = Decimal('9999')
        self.product.save()
        self.sc.post(f'/confirm-order/{order.id}/')
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Decimal('550.00'))

    def test_reject_deletes_and_notifies(self):
        order = self.place_order()
        self.assertEqual(self.sc.get(f'/reject-order/{order.id}/').status_code, 405)
        self.assertTrue(Order.objects.filter(id=order.id).exists())
        self.sc.post(f'/reject-order/{order.id}/')
        self.assertFalse(Order.objects.filter(id=order.id).exists())
        self.assertIn('rejected', Notification.objects.get(user=self.buyer).message)

    def test_confirmed_order_cannot_be_rejected(self):
        order = self.place_order()
        self.sc.post(f'/confirm-order/{order.id}/')
        self.sc.post(f'/reject-order/{order.id}/')
        self.assertTrue(Order.objects.filter(id=order.id).exists())

    def test_other_seller_cannot_touch_order(self):
        order = self.place_order()
        other = self.as_user(self.other_seller)
        self.assertEqual(other.post(f'/confirm-order/{order.id}/').status_code, 404)
        self.assertEqual(other.post(f'/reject-order/{order.id}/').status_code, 404)

    def test_buyer_cannot_confirm(self):
        order = self.place_order()
        self.bc.post(f'/confirm-order/{order.id}/')
        order.refresh_from_db()
        self.assertFalse(order.confirmed)


class ReviewAndNotificationTests(MarketTestCase):
    def test_review_form_saves_and_shows(self):
        self.assertContains(self.bc.get(f'/reviews/{self.product.id}/'), 'No reviews yet')
        r = self.bc.post(f'/review/{self.product.id}/', {'comment': 'Lovely', 'rating': '4'}, follow=True)
        self.assertContains(r, 'Lovely')
        self.assertContains(r, 'Review submitted!')
        self.assertContains(r, 'Average rating: 4.0/5')

    def test_rating_is_optional(self):
        self.bc.post(f'/review/{self.product.id}/', {'comment': 'No stars'})
        self.assertIsNone(Review.objects.get().rating)

    def test_invalid_reviews_are_rejected_and_keep_text(self):
        for data in ({'comment': 'x', 'rating': 'abc'}, {'comment': 'x', 'rating': '99'}, {'comment': 'x', 'rating': '0'},
                     {'comment': '   ', 'rating': '3'}):
            r = self.bc.post(f'/review/{self.product.id}/', data)
            self.assertEqual(r.status_code, 200)
        self.assertEqual(Review.objects.count(), 0)
        r = self.bc.post(f'/review/{self.product.id}/', {'comment': 'keep me', 'rating': '99'})
        self.assertContains(r, 'keep me')

    def test_get_submit_review_redirects(self):
        self.assertRedirects(self.bc.get(f'/review/{self.product.id}/'), f'/reviews/{self.product.id}/')

    def test_seller_sees_reviews_with_date_product_and_rating(self):
        Review.objects.create(product=self.product, buyer=self.buyer, comment='Datecheck', rating=5)
        page = self.sc.get('/seller/dashboard/').content.decode()
        self.assertIn('Datecheck', page)
        self.assertIn('5/5', page)
        self.assertRegex(page, r'Date:</strong> \w{3} \d{2}, \d{4}')

    def test_notifications_page_marks_read(self):
        Notification.objects.create(user=self.buyer, message='Hello there')
        self.assertContains(self.bc.get('/buyer/dashboard/'), 'badge bg-danger')
        first = self.bc.get('/notifications/')
        self.assertContains(first, 'Hello there')
        self.assertContains(first, 'New')
        self.assertNotContains(self.bc.get('/notifications/'), '>New<')
        self.assertTrue(Notification.objects.get().is_read)

    def test_notifications_empty_state(self):
        self.assertContains(self.bc.get('/notifications/'), 'No notifications available')


class EndToEndWithCsrfTests(MarketTestCase):
    """Drives the real HTML forms with CSRF protection ON, so a missing {% csrf_token %} fails here."""

    def token(self, client, url):
        html = client.get(url).content.decode()
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        self.assertIsNotNone(match, f'no CSRF token on {url}')
        return match.group(1)

    def post(self, client, from_page, url, data):
        data = {**data, 'csrfmiddlewaretoken': self.token(client, from_page)}
        return client.post(url, data, follow=True)

    def test_whole_marketplace_journey(self):
        seller = Client(enforce_csrf_checks=True)
        buyer = Client(enforce_csrf_checks=True)

        # seller signs up, picks a role and uploads a product
        r = self.post(seller, '/signup/', '/signup/', {'username': 'artisan', 'email': 'a@example.com', 'password': PASSWORD})
        self.assertContains(r, 'Select Your Role')
        r = self.post(seller, '/select-role/', '/select-role/', {'role': 'seller'})
        self.assertContains(r, 'Welcome to Seller Dashboard')
        r = self.post(seller, '/seller/dashboard/', '/seller/dashboard/',
                      {'upload_product': '1', 'name': 'Teapot', 'price': '800', 'image': make_image()})
        self.assertContains(r, 'Product uploaded successfully')
        product = Product.objects.get(name='Teapot')

        # buyer signs up, searches, wishlists, carts, orders
        self.post(buyer, '/signup/', '/signup/', {'username': 'shopper', 'email': 's@example.com', 'password': PASSWORD})
        self.post(buyer, '/select-role/', '/select-role/', {'role': 'buyer'})
        self.assertContains(buyer.get('/buyer/dashboard/?q=tea'), 'Teapot')
        self.post(buyer, '/buyer/dashboard/', f'/wishlist/add/{product.id}/', {})
        self.post(buyer, '/buyer/dashboard/', f'/cart/add/{product.id}/', {})
        self.assertContains(buyer.get('/cart/'), 'Teapot')
        r = buyer.get(f'/order/{product.id}/', follow=True)
        self.assertContains(r, 'Review Your Order')
        r = self.post(buyer, f'/review-order/{product.id}/', f'/review-order/{product.id}/',
                      {'address': '7 Temple Road, Thanjavur', 'mobile': '9876543210'})
        self.assertContains(r, 'Choose Payment Method')
        r = self.post(buyer, '/payment/', '/payment/', {'payment_method': 'phonepe'})
        self.assertContains(r, 'Order Placed Successfully')

        # seller confirms through the dashboard button
        self.assertContains(seller.get('/seller/dashboard/'), '7 Temple Road')
        order = Order.objects.get()
        r = self.post(seller, '/seller/dashboard/', f'/confirm-order/{order.id}/', {})
        self.assertContains(r, 'confirmed')

        # buyer sees notification, order status, and leaves a review
        self.assertContains(buyer.get('/notifications/'), 'was confirmed')
        self.assertContains(buyer.get('/orders/'), 'Confirmed')
        r = self.post(buyer, f'/reviews/{product.id}/', f'/review/{product.id}/', {'comment': 'Perfect', 'rating': '5'})
        self.assertContains(r, 'Perfect')
        self.assertContains(seller.get('/seller/dashboard/'), 'Perfect')

        # delete and logout
        r = self.post(seller, '/seller/dashboard/', f'/product/delete/{product.id}/', {})
        self.assertContains(r, 'Product deleted successfully')
        for c in (seller, buyer):
            self.assertRedirects(c.get('/logout/'), '/')

    def test_post_without_token_is_rejected(self):
        c = Client(enforce_csrf_checks=True)
        c.login(username='seller', password=PASSWORD)
        self.assertEqual(c.post(f'/product/delete/{self.product.id}/').status_code, 403)


class AdminAndMigrationTests(MarketTestCase):
    def test_models_are_registered_and_admin_pages_load(self):
        admin_user = User.objects.create_superuser('root', 'r@example.com', PASSWORD)
        c = self.as_user(admin_user)
        for model in ('profile', 'product', 'order', 'review', 'notification', 'wishlist', 'cart'):
            self.assertEqual(c.get(f'/admin/store/{model}/').status_code, 200, model)

    def test_order_status_property_and_querysets(self):
        order = Order.objects.create(buyer=self.buyer, product=self.product)
        self.assertEqual(order.status, 'Pending')
        self.assertEqual(Order.objects.drafts().count(), 1)
        order.payment_method = 'cod'
        order.save()
        self.assertEqual(Order.objects.placed().count(), 1)
        self.assertEqual(Order.objects.drafts().count(), 0)
        order.payment_method = ''
        order.save()
        self.assertEqual(Order.objects.drafts().count(), 1)

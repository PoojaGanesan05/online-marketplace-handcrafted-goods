from django.db import migrations

# Orders placed before the payment form was fixed stored the label that was
# shown on screen. Convert them to the codes the Order model expects.
LABEL_TO_CODE = {
    'UPI-GPay': 'gpay',
    'GPay': 'gpay',
    'UPI-PhonePe': 'phonepe',
    'PhonePe': 'phonepe',
    'Cash on Delivery': 'cod',
}


def labels_to_codes(apps, schema_editor):
    Order = apps.get_model('store', 'Order')
    for label, code in LABEL_TO_CODE.items():
        Order.objects.filter(payment_method=label).update(payment_method=code)


def codes_to_labels(apps, schema_editor):
    # Reverse step keeps the data as it was originally displayed.
    Order = apps.get_model('store', 'Order')
    Order.objects.filter(payment_method='gpay').update(payment_method='UPI-GPay')
    Order.objects.filter(payment_method='phonepe').update(payment_method='UPI-PhonePe')
    Order.objects.filter(payment_method='cod').update(payment_method='Cash on Delivery')


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0005_order_delivery_address_order_delivery_charge_and_more'),
    ]

    operations = [
        migrations.RunPython(labels_to_codes, codes_to_labels),
    ]

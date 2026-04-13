import qrcode
from io import BytesIO
from django.core.files.base import ContentFile
from django.conf import settings
import os

def generate_product_qr_code(product):
    if not product.slug:
        raise ValueError("Product slug is required for QR code generation")

    qr_data = f"{settings.FRONTEND_URL}/products/{product.slug}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    filename = f"qr_{product.slug}.png"
    product.qr_code.save(filename, ContentFile(buffer.read()), save=False)

    return product.qr_code.url
    
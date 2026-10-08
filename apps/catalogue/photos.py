"""Photo processing: every upload is re-encoded, which strips EXIF data such as GPS location."""
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_IMAGE_SIZE = (1600, 1600)
THUMBNAIL_SIZE = (480, 360)


def _encode_jpeg(image, size):
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    buffer = BytesIO()
    copy.save(buffer, format='JPEG', quality=85, optimize=True)
    return buffer.getvalue()


def process_upload(uploaded_file):
    """Return (image ContentFile, thumbnail ContentFile) as upright, metadata-free JPEGs."""
    uploaded_file.seek(0)
    with Image.open(uploaded_file) as original:
        upright = ImageOps.exif_transpose(original)
        if upright.mode in ('RGBA', 'LA', 'P'):
            upright = upright.convert('RGBA')
            background = Image.new('RGB', upright.size, (255, 255, 255))
            background.paste(upright, mask=upright.split()[-1])
            image = background
        else:
            image = upright.convert('RGB')
    name = f'{uuid4().hex}.jpg'
    image_file = ContentFile(_encode_jpeg(image, MAX_IMAGE_SIZE), name=name)
    thumbnail_file = ContentFile(_encode_jpeg(image, THUMBNAIL_SIZE), name=f'{Path(name).stem}-thumb.jpg')
    return image_file, thumbnail_file

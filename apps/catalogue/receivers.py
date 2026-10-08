from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ProductPhoto


@receiver(post_delete, sender=ProductPhoto)
def delete_photo_files(sender, instance, **kwargs):
    """Remove the stored files with the row (including when a whole product is deleted)."""
    for field in (instance.image, instance.thumbnail):
        if field.name:
            field.storage.delete(field.name)

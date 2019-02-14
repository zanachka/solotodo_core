from django.db import models

from banners.models import BannerUpdate, BannerAsset
from solotodo.models import Category, Store


class BannerQuerySet(models.QuerySet):
    def filter_by_user_perms(self, user, permission):
        stores_with_permissions = Store.objects.filter_by_user_perms(
            user, permission)

        return self.filter(
            update__store__in=stores_with_permissions
        )


class Banner(models.Model):
    update = models.ForeignKey(BannerUpdate, on_delete=models.CASCADE)
    asset = models.ForeignKey(BannerAsset, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE,
                                 null=True, blank=True)
    position = models.IntegerField()
    objects = BannerQuerySet.as_manager()

    def __str__(self):
        return '{} - {} - {} - {}'.format(self.update, self.asset,
                                          self.category, self.position)

    class Meta:
        app_label = 'banners'
        ordering = ('update', 'asset', 'category')
        permissions = (
            ['backend_list_banners', 'Can see banner list in the backend'],
        )

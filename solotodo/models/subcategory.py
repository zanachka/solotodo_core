from django.db import models

from .category import Category


class Subcategory(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    params = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.category} - {self.name}"

    class Meta:
        app_label = "solotodo"
        ordering = ("category", "name")

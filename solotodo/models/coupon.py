from decimal import Decimal

from django.db import models

from .store import Store
from .category import Category


class Coupon(models.Model):
    RAW_AMOUNT = 1
    PERCENTAGE = 2

    AMOUNT_TYPE_CHOICES = [
        (RAW_AMOUNT, "Raw amount"),
        (PERCENTAGE, "Percentage"),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    categories = models.ManyToManyField(Category, blank=True)
    entities = models.ManyToManyField("Entity", blank=True)
    code = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_type = models.IntegerField(choices=AMOUNT_TYPE_CHOICES)
    max_discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    def amount_type_text(self):
        return next(x for x in self.AMOUNT_TYPE_CHOICES if x[0] == self.amount_type)[1]

    def __str__(self):
        return "{} - {} - {} - {}".format(
            self.store, self.code, self.amount, self.amount_type_text()
        )

    def apply(self):
        from solotodo.models import Entity

        es = (
            Entity.objects.get_active()
            .filter(store=self.store)
            .exclude(best_coupon=self)
            .select_related("active_registry")
        )

        if self.categories.all():
            es = es.filter(category__in=self.categories.all())

        if self.entities.all():
            es = es.filter(pk__in=self.entities.all())

        # Hardcoded logic for LG coupon, delete this once the coupon with the given ID no longer exists
        if self.id == 2080:
            # blacklisted_skus = [
            # "GS66SXTC.AMCPECL.ESCL.CL.C",
            # "GS66WPP.APZPECL.ESCL.CL.C",
            # "WD12VVC4S6C.APTPECL.ESCL.CL.C",
            # "WK14BS6.APBPECL.ESCL.CL.C",
            # "WK22BS6.ABLPECL.ESCL.CL.C",
            # "WT19MPB.ABMPECL.ESCL.CL.C",
            # ]
            es = es.exclude(category=4)

        for e in es:
            price_with_coupon = self.calculate_price(e.active_registry.offer_price)

            if e.best_coupon:
                # Check if opur coupon provides a better discount
                price_with_current_coupon = e.best_coupon.calculate_price(
                    e.active_registry.offer_price
                )
                if price_with_current_coupon < price_with_coupon:
                    continue

            print("Applying coupon to {}".format(e))
            e.best_coupon = self
            e.save()

    def calculate_price(self, price_value):
        if self.amount_type == self.RAW_AMOUNT:
            discount = self.amount
        elif self.amount_type == self.PERCENTAGE:
            discount = price_value * (self.amount / Decimal(100))
        else:
            raise Exception("Invalid amount type")

        if self.max_discount_amount and discount > self.max_discount_amount:
            discount = self.max_discount_amount

        return price_value - discount

    @classmethod
    def apply_all_coupons(cls):
        for coupon in cls.objects.all():
            coupon.apply()

    class Meta:
        app_label = "solotodo"
        ordering = ("-pk",)

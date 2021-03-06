import collections
import hashlib
import json

from decimal import Decimal

from elasticsearch_dsl.aggs import Bucket

import datetime


def iterable_to_dict(iterable_or_model, field='id'):
    if not isinstance(iterable_or_model, collections.Iterable):
        iterable_or_model = iterable_or_model.objects.all()

    return {getattr(e, field): e for e in iterable_or_model}


# REF: https://stackoverflow.com/questions/4581789/how-do-i-get-user-ip-
# address-in-django
# Yes, I know this can be spoofed, but hopefully it is only used for
# convenience
def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def format_currency(value, curr='$', places=2, sep='.', dp=','):
    """Convert Decimal to a money formatted string.

    curr: optional currency symbol before the sign (may be blank)
    sep: optional grouping separator (comma, period, space, or blank)
    dp: decimal point indicator (comma or period)
    only specify as blank when places is zero

    """
    quantized_precision = Decimal(10) ** -places  # 2 places --> '0.01'
    sign, digits, exp = value.quantize(quantized_precision).as_tuple()
    result = []
    digits = list(map(str, digits))
    build, iter_next = result.append, digits.pop

    for i in range(places):
        build(iter_next() if digits else '0')
    if places:
        build(dp)
    if not digits:
        build('0')
    i = 0
    while digits:
        build(iter_next())
        i += 1
        if i == 3 and digits:
            i = 0
            build(sep)
    build(curr)

    return ''.join(reversed(result))


def generate_cache_key(cache_dict):
    return hashlib.sha1(json.dumps(cache_dict).encode('utf-8')).hexdigest()


class Clock(object):
    def __init__(self):
        import time
        self.time = time.monotonic()

    def tick(self, label):
        import time
        new_time = time.monotonic()
        print('{}: {}'.format(label, new_time - self.time))
        self.time = new_time


# REF https://stackoverflow.com/questions/304256/whats-the-best-way-to-
# find-the-inverse-of-datetime-isocalendar
def iso_year_start(iso_year):
    "The gregorian calendar date of the first day of the given ISO year"
    fourth_jan = datetime.datetime(iso_year, 1, 4)
    delta = datetime.timedelta(fourth_jan.isoweekday()-1)
    return fourth_jan - delta


def iso_to_gregorian(iso_year, iso_week, iso_day):
    "Gregorian calendar date for the given ISO year, week and day"
    year_start = iso_year_start(iso_year)
    return year_start + datetime.timedelta(days=iso_day-1, weeks=iso_week-1)


class Parent(Bucket):
    name = 'parent'

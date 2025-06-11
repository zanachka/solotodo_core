import requests
from django.conf import settings
from django.core.management import BaseCommand

from solotodo.models import Store
from upstash_redis import Redis
from storescraper.utils import chunks


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--cookie", type=str)

    def handle(self, *args, **options):
        print("*", options["cookie"])
        s = Store.objects.get(name="Mercado Libre")
        redis = Redis(
            url=settings.UPSTASH_REDIS_REST_URL, token=settings.UPSTASH_REDIS_REST_TOKEN
        )
        pending_urls = [
            e.url for e in s.entity_set.get_active() if not redis.get(e.url)
        ]
        session = requests.Session()
        print(options["cookie"])
        session.headers["Cookie"] = options["cookie"]
        session.headers["Origin"] = "https://www.mercadolibre.cl"
        session.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:139.0) Gecko/20100101 Firefox/139.0"
        )
        url_chunks = list(chunks(pending_urls, 30))
        for url_chunk in url_chunks:
            payload = {"urls": url_chunk, "tag": "vijkhemlani"}
            res = session.post(
                "https://www.mercadolibre.cl/affiliate-program/api/v2/affiliates/createLink",
                json=payload,
            )
            res_json = res.json()
            for idx, my_url in enumerate(url_chunk):
                res_entry = res_json["urls"][idx]
                if "short_url" in res_entry:
                    redis.set(my_url, res_entry["short_url"])
                    print(my_url, "->", res_entry["short_url"])

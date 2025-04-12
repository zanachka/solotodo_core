from django.core.mail import send_mail
from django.core.management import BaseCommand

from storescraper.stores import LgCl

from storescraper.utils import session_with_proxy

from solotodo.models import SoloTodoUser


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            extra_args = LgCl.preflight()
            target_url = "https://www.lg.com/cl/tvs-y-soundbars/4k-uhd-tvs/55ut8050psb/"
            session = session_with_proxy(extra_args)
            response = session.get(target_url)
            checks = [
                "198646195fd16dfedce75f3ff6bc8708",
                "05f1c07042a0ecf10800978c8646f751",
                "edd239717c86",
            ]
            for check in checks:
                if check not in response.text:
                    raise Exception(f"{check} not found in {target_url}")

            print("Checks OK")
        except Exception as e:
            email_recipients = [
                x.email_recipient_text()
                for x in SoloTodoUser.objects.filter(is_superuser=True)
            ]

            send_mail(
                "Error detecting LG PDP assets",
                str(e),
                SoloTodoUser().get_bot().email_recipient_text(),
                email_recipients,
            )

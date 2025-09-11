from rest_framework import routers

from reports.views import ReportViewSet, ReportDownloadViewSet

router = routers.SimpleRouter()
router.register("reports", ReportViewSet)
router.register("report_downloads", ReportDownloadViewSet)

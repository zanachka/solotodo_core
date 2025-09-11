from rest_framework import serializers

from reports.models import Report, ReportDownload
from solotodo.serializers import UserSerializer


class ReportSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Report
        fields = ("url", "id", "name", "slug")


class ReportDownloadSerializer(serializers.HyperlinkedModelSerializer):
    report = ReportSerializer()
    user = UserSerializer()

    class Meta:
        model = ReportDownload
        fields = ("url", "id", "report", "user", "timestamp", "status")

import os
import json
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from django.conf import settings

class GoogleAnalyticsService:
    def __init__(self):
        self.property_id = settings.GA4_PROPERTY_ID
        
        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if creds_json:
            creds_info = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(creds_info)
            self.client = BetaAnalyticsDataClient(credentials=credentials)
        else:
            # The client automatically picks up GOOGLE_APPLICATION_CREDENTIALS from env locally
            self.client = BetaAnalyticsDataClient()

    def get_active_users(self, days=30):
        """Fetches total active users over the given time period."""
        if not self.property_id:
            return 0
            
        try:
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
                dimensions=[],
                metrics=[Metric(name="activeUsers")],
                date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
            )
            response = self.client.run_report(request)
            
            for row in response.rows:
                return int(row.metric_values[0].value)
            return 0
        except Exception as e:
            print(f"GA4 Error active_users: {e}")
            return 0

    def get_most_viewed_pages(self, days=30, limit=5):
        """Fetches the most viewed pages over the given time period."""
        if not self.property_id:
            return []
            
        try:
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
                dimensions=[Dimension(name="pagePath")],
                metrics=[Metric(name="screenPageViews")],
                date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
            )
            response = self.client.run_report(request)
            
            results = []
            for row in response.rows:
                results.append({
                    "path": row.dimension_values[0].value,
                    "views": int(row.metric_values[0].value)
                })
                
            # Sort by views descending
            results.sort(key=lambda x: x["views"], reverse=True)
            return results[:limit]
        except Exception as e:
            print(f"GA4 Error most_viewed_pages: {e}")
            return []

import datetime
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from base.models import Order

class DashboardService:
    def __init__(self):
        # We include 'pending' for COD orders, and the standard success statuses.
        # Exclude 'cancelled', 'refunded', 'awaiting_payment'
        self.valid_statuses = ['pending', 'paid', 'shipped', 'delivered']

    def _get_base_queryset(self):
        return Order.objects.filter(status__in=self.valid_statuses)

    def _calculate_change_percentage(self, current, previous):
        if previous == 0:
            return 0.0
        return round(((current - previous) / previous) * 100, 2)

    def _get_summary_stats(self, start_date, end_date):
        qs = self._get_base_queryset().filter(created_at__range=(start_date, end_date))
        agg = qs.aggregate(
            order_count=Count('id'),
            total_revenue=Sum('payment__amount')
        )
        
        order_count = agg['order_count'] or 0
        total_revenue = float(agg['total_revenue'] or 0.0)
        average_order_value = round(total_revenue / order_count, 2) if order_count > 0 else 0.0
        
        return {
            'order_count': order_count,
            'total_revenue': total_revenue,
            'average_order_value': average_order_value
        }

    def _get_daily_chart(self, today_start):
        days = 7
        start_date = today_start - datetime.timedelta(days=days-1)
        qs = self._get_base_queryset().filter(created_at__gte=start_date).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            order_count=Count('id'),
            total_revenue=Sum('payment__amount')
        ).order_by('date')
        
        data_dict = {item['date']: item for item in qs if item['date']}
        
        result = []
        for i in range(days):
            current_date = (start_date + datetime.timedelta(days=i)).date()
            # TruncDate returns date objects
            if current_date in data_dict:
                result.append({
                    "date": current_date.isoformat(),
                    "order_count": data_dict[current_date]['order_count'],
                    "total_revenue": float(data_dict[current_date]['total_revenue'] or 0.0)
                })
            else:
                result.append({
                    "date": current_date.isoformat(),
                    "order_count": 0,
                    "total_revenue": 0.0
                })
        return result

    def _get_weekly_chart(self, this_week_start):
        weeks = 4
        start_date = this_week_start - datetime.timedelta(days=7*(weeks-1))
        
        qs = self._get_base_queryset().filter(created_at__gte=start_date).annotate(
            week=TruncWeek('created_at')
        ).values('week').annotate(
            order_count=Count('id'),
            total_revenue=Sum('payment__amount')
        ).order_by('week')
        
        # TruncWeek can return datetime in some DBs, convert to date just in case
        data_dict = {
            (item['week'].date() if hasattr(item['week'], 'date') else item['week']): item 
            for item in qs if item['week']
        }
        
        result = []
        for i in range(weeks):
            current_week_start = (start_date + datetime.timedelta(days=7*i)).date()
            if current_week_start in data_dict:
                result.append({
                    "week": current_week_start.isoformat(),
                    "order_count": data_dict[current_week_start]['order_count'],
                    "total_revenue": float(data_dict[current_week_start]['total_revenue'] or 0.0)
                })
            else:
                result.append({
                    "week": current_week_start.isoformat(),
                    "order_count": 0,
                    "total_revenue": 0.0
                })
        return result

    def _get_monthly_chart(self, this_month_start):
        months = 6
        
        temp_date = this_month_start
        for _ in range(months - 1):
            if temp_date.month == 1:
                temp_date = temp_date.replace(year=temp_date.year - 1, month=12)
            else:
                temp_date = temp_date.replace(month=temp_date.month - 1)
        start_date = temp_date
        
        qs = self._get_base_queryset().filter(created_at__gte=start_date).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            order_count=Count('id'),
            total_revenue=Sum('payment__amount')
        ).order_by('month')
        
        data_dict = {
            (item['month'].date() if hasattr(item['month'], 'date') else item['month']): item 
            for item in qs if item['month']
        }
        
        result = []
        current = start_date.date()
        for i in range(months):
            if current in data_dict:
                result.append({
                    "month": current.isoformat()[:7],  # YYYY-MM
                    "order_count": data_dict[current]['order_count'],
                    "total_revenue": float(data_dict[current]['total_revenue'] or 0.0)
                })
            else:
                result.append({
                    "month": current.isoformat()[:7],
                    "order_count": 0,
                    "total_revenue": 0.0
                })
            # Increment month safely
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
                
        return result

    def get_dashboard_analytics(self) -> dict:
        now = timezone.localtime(timezone.now())
        
        # Today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + datetime.timedelta(days=1)
        
        # Yesterday
        yesterday_start = today_start - datetime.timedelta(days=1)
        
        # This Week (Monday start)
        this_week_start = today_start - datetime.timedelta(days=today_start.weekday())
        last_week_start = this_week_start - datetime.timedelta(days=7)
        
        # This Month
        this_month_start = today_start.replace(day=1)
        if this_month_start.month == 1:
            last_month_start = this_month_start.replace(year=this_month_start.year - 1, month=12)
        else:
            last_month_start = this_month_start.replace(month=this_month_start.month - 1)
        last_month_end = this_month_start
        
        # Summaries
        today_stats = self._get_summary_stats(today_start, today_end)
        yesterday_stats = self._get_summary_stats(yesterday_start, today_start)
        
        this_week_stats = self._get_summary_stats(this_week_start, today_end)
        last_week_stats = self._get_summary_stats(last_week_start, this_week_start)
        
        this_month_stats = self._get_summary_stats(this_month_start, today_end)
        last_month_stats = self._get_summary_stats(last_month_start, last_month_end)

        return {
            "summary": {
                "today": today_stats,
                "yesterday": yesterday_stats,
                "today_vs_yesterday": {
                    "order_count_change_percentage": self._calculate_change_percentage(today_stats['order_count'], yesterday_stats['order_count']),
                    "revenue_change_percentage": self._calculate_change_percentage(today_stats['total_revenue'], yesterday_stats['total_revenue']),
                    "aov_change_percentage": self._calculate_change_percentage(today_stats['average_order_value'], yesterday_stats['average_order_value']),
                },
                "this_week": this_week_stats,
                "last_week": last_week_stats,
                "this_week_vs_last_week": {
                    "order_count_change_percentage": self._calculate_change_percentage(this_week_stats['order_count'], last_week_stats['order_count']),
                    "revenue_change_percentage": self._calculate_change_percentage(this_week_stats['total_revenue'], last_week_stats['total_revenue']),
                    "aov_change_percentage": self._calculate_change_percentage(this_week_stats['average_order_value'], last_week_stats['average_order_value']),
                },
                "this_month": this_month_stats,
                "last_month": last_month_stats,
                "this_month_vs_last_month": {
                    "order_count_change_percentage": self._calculate_change_percentage(this_month_stats['order_count'], last_month_stats['order_count']),
                    "revenue_change_percentage": self._calculate_change_percentage(this_month_stats['total_revenue'], last_month_stats['total_revenue']),
                    "aov_change_percentage": self._calculate_change_percentage(this_month_stats['average_order_value'], last_month_stats['average_order_value']),
                }
            },
            "charts": {
                "daily": self._get_daily_chart(today_start),
                "weekly": self._get_weekly_chart(this_week_start),
                "monthly": self._get_monthly_chart(this_month_start)
            }
        }

# 確保 Django 啟動時 Celery App 一併就緒
from .celery import app as celery_app
__all__ = ('celery_app',)

"""
config/celery.py
Celery 應用初始化，整合 Django settings。
"""
import os
from celery import Celery

# 設定 Django settings 環境變數
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('signoff_system')

# 從 Django settings 讀取所有 CELERY_ 前綴的設定
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自動發現所有 app 底下的 tasks.py
app.autodiscover_tasks()

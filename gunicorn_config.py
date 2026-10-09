bind = "0.0.0.0:5000"
# 同步进度存在进程内存（sync_progress 字典），必须单 worker + 多 threads，
# 否则前端轮询会命中不同 worker 拿不到进度。同步是 IO 密集型，threads 足够。
workers = 1
threads = 8
timeout = 1800
accesslog = "-"
errorlog = "-"

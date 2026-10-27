FROM python:3.13-slim@sha256:b3575dcf816cdacc5292df77a6e3e59b8941631078373a045efa2ac1e9c5c3b2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SHIZHI_DATA_DIR=/data
WORKDIR /app
COPY web /app/web
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2).read()"]
ENTRYPOINT ["python", "-m", "web.controller"]
CMD ["--host", "0.0.0.0", "--port", "8765"]

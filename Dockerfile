FROM continuumio/miniconda3:25.3.1-1
WORKDIR /app
COPY environment.yml requirements.txt ./
RUN conda env create --name artifact-health-record --file environment.yml && conda clean --all --yes
ENV PATH=/opt/conda/envs/artifact-health-record/bin:$PATH
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm ci --no-audit --no-fund
COPY . .
RUN cd frontend && npm run build
RUN useradd --uid 10001 --create-home ahr && mkdir -p /app/runtime && chown -R ahr:ahr /app
USER ahr
ENV AHR_HOST=0.0.0.0 AHR_PORT=8765 PYTHONUNBUFFERED=1
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health',timeout=4)"
CMD ["python", "run.py", "serve", "--host", "0.0.0.0"]


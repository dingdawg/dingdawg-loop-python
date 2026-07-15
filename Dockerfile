FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml ./
COPY dingdawg_loop ./dingdawg_loop
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/dist/*.whl ./
RUN pip install --no-cache-dir *.whl
ENTRYPOINT ["python", "-m", "dingdawg_loop"]

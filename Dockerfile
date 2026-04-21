FROM python:3.12-slim

WORKDIR /app

# install uv
RUN pip install uv

# copy dependency files first (better caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# copy source code
COPY src ./src

# make sure Python can find your package
ENV PYTHONPATH=/app/src

# run your module
CMD ["uv", "run", "tibber_power"]
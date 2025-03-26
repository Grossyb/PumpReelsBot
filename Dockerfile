FROM python:3.9.12-slim-bullseye

# Initialize the Python environment
RUN python -m pip install --upgrade pip
RUN pip install poetry==1.4.2
COPY poetry.lock pyproject.toml /
RUN poetry config virtualenvs.create false \
  && poetry install --no-dev --no-interaction --no-ansi

COPY api /code/
WORKDIR /code

RUN groupadd -g 1000 basicuser && \
  useradd -r -u 1000 -g basicuser basicuser
USER basicuser

EXPOSE 5000

# Run the application.
CMD uvicorn 'main:app' --host=0.0.0.0 --port=5000

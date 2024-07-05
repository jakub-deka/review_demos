FROM jupyter/datascience-notebook:x86_64-latest

ENV JUPYTER_ALLOW_INSECURE_WRITES=1

COPY ./requirements.txt requirements.txt
RUN pip install -Ur requirements.txt
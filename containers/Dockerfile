FROM tigrlab/datman:0.2.1 as prod

# NOTE: When building this container, do it from
# inside the dashboard folder and build with
#       docker build -f containers/Dockerfile .
# or the build context will be incorrect and files may not
# be copied

COPY containers/entrypoint.sh /entrypoint.sh

# Copy the requirements and set up the python env first so
# that rebuilds are faster.
COPY ./requirements.txt /

# Install requirements for pip installing uwsgi
RUN apt update && \
    apt install -y --no-install-recommends gcc python3.11-dev

RUN pip install --upgrade pip && \
    pip install -r /requirements.txt

ENV PATH="/dashboard:${PATH}"
ENV PYTHONPATH="/dashboard:${PYTHONPATH}"

COPY . /dashboard

CMD ["uwsgi", \
        "--socket=0.0.0.0:5000", \
        "--protocol=http", \
        "--wsgi-file=/dashboard/wsgi.py", \
        "--callable=app", \
        "--enable-threads"]

FROM prod as devel
RUN pip install flask-debugtoolbar \
                pytest \
                sqlalchemy-utils

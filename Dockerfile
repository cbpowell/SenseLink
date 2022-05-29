FROM python:3.10-slim
MAINTAINER Charles Powell <cbpowell@gmail.com>

# Install all dependencies
ADD . /senselink
RUN pip install /senselink --use-feature=in-tree-build

# Make non-root user
RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

# Run
CMD ["python", "-m", "senselink"]
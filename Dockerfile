FROM python:3.10-slim
MAINTAINER Charles Powell <cbpowell@gmail.com>

# Install all dependencies
RUN pip install senselink

# Make non-root user
RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

# Run
CMD ["python", "-m", "senselink"]
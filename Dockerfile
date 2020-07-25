FROM python:3.7-stretch
MAINTAINER Charles Powell <cbpowell@gmailcom>

# Install all dependencies
COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt

# Make non-root user
RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

# Add all other files
COPY . .

# Run
CMD ["python", "-m", "SenseLink"]
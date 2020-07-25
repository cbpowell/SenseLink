FROM python:3.7-stretch
MAINTAINER Charles Powell <cbpowell@gmailcom>

# Make non-root user
RUN useradd --create-home appuser
WORKDIR /home/appuser
USER appuser

# Install all dependencies
ADD requirements.txt .
RUN pip install -r requirements.txt

# Add all other files
ADD . .

# Run
CMD ["python", "-m", "SenseLink"]
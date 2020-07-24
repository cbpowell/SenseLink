FROM python:3
MAINTAINER Charles Powell <cbpowell@gmailcom>

# Add all files
ADD .

# Install all dependencies
RUN pip install -r requirements.txt

# Run
CMD ["python", "-m", "SenseLink"]
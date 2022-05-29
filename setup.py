from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name='SenseLink',
    version='2.0.3',
    description='A tool to create virtual smart plugs and inform a Sense Home Energy Monitor about usage in your home',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://github.com/cbpowell/SenseLink',
    author='Charles Powell',
    author_email='cbpowell@gmail.com',
    license='MIT',
    packages=find_packages(),
    install_requires=['asyncio-mqtt>=0.12.1',
                      'dpath>=2.0.6',
                      'paho-mqtt>=1.6.1',
                      'PyYAML>=6.0',
                      'websockets>=10.2'
                      ],

    classifiers=[
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9'
    ],
)
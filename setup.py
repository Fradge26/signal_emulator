from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="signal_emulator",
    version="0.0.10",
    author="Adam Fradgley",
    author_email="adamfradgley@tfl.gov.uk",
    description="TfL Traffic Signal Timings Generator",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Fradge26/signal_emulator",
    project_urls={"Bug Tracker": "https://github.com/Fradge26/signal_emulator/issues"},
    license="None",
    packages=find_packages(),
    install_requires=requirements,
)

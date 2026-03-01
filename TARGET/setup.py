"""
Setup script for AI Desktop Copilot.
"""
from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="ai-desktop-copilot",
    version="1.0.0",
    description="AI Desktop Copilot - Natural Language to SQL Query Engine",
    author="AI Desktop Copilot Team",
    packages=find_packages(),
    install_requires=requirements,
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "ai-copilot=backend.main:run_server",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)

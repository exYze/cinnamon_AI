from setuptools import setup, find_packages

setup(
    name="nexus-directory",
    version="0.1.0",
    description="NexusOS Directory Service — AD-compatible identity provider",
    author="NexusOS Team",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "ldap3>=2.9",
        "pydantic>=2.0",
        "click>=8.1",
        "rich>=13.0",
    ],
    entry_points={
        "console_scripts": [
            "nexus-directory=nexus_directory.server:main",
        ],
    },
)

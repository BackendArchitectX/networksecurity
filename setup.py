from pathlib import Path

from setuptools import find_packages, setup


def requirements() -> list[str]:
    return [
        line.strip()
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


setup(
    name="network-security-decision-platform",
    version="3.0.0",
    description=(
        "Threat-scoring serving plane with immutable model bundles and a durable "
        "asynchronous training control plane"
    ),
    author="Pranay Kadu",
    packages=find_packages(),
    python_requires=">=3.12",
    install_requires=requirements(),
)

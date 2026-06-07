from setuptools import setup, find_packages

setup(
    name="phonectl",
    version="0.1.0",
    description="Universal Android Phone Lifecycle Manager",
    author="psahoo",
    license="Apache-2.0",
    packages=find_packages(),
    include_package_data=True,
    package_data={"phonectl": ["config/*.yaml"]},
    install_requires=[
        "click>=8.1",
        "rich>=13.0",
        "PyYAML>=6.0",
        "requests>=2.31",
    ],
    entry_points={
        "console_scripts": [
            "phonectl=phonectl.cli:cli",
        ],
    },
    python_requires=">=3.10",
)

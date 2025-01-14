from setuptools import setup, find_packages

setup(
    name="mkdocs-translator",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        'openai>=1.0.0',
        'click>=8.0.0',
        'pyyaml>=6.0.0',
        'tqdm>=4.65.0',
        'pathlib>=1.0.1',
    ],
    entry_points={
        'console_scripts': [
            'mkdocs-translator=mkdocs_translator.cli:translate',
        ],
    },
    author="Your Name",
    author_email="your.email@example.com",
    description="A tool for translating MkDocs documentation",
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/mkdocs-translator",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.9',
) 
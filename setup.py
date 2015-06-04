#!/usr/bin/python

from setuptools import setup, find_packages

setup(
    name='conftool',
    version='0.0.1',
    description='Collection of tools to interoperate with distributed k/v stores',
    author='Joe',
    author_email='glavagetto@wikimedia.org',
    url='https://github.com/wikimedia/operations-software-conftool',
    install_requires=['python-etcd', 'yaml'],
    setup_requires=[],
    zip_safe=True,
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'conftool-sync = conftool.cli.syncer:main',
            'confctl = conftool.cli.tool:main',
        ],
    },
)

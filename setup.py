#!/usr/bin/python

from setuptools import setup, find_packages

setup(
    name='conftool',
    version='1.1.3',
    description='Tools to interoperate with distributed k/v stores',
    author='Joe',
    author_email='joe@wikimedia.org',
    url='https://github.com/wikimedia/operations-software-conftool',
    install_requires=['python-etcd>=0.4.3', 'pyyaml', 'jsonschema'],
    test_suite='nose.collector',
    tests_require=['nose'],
    zip_safe=False,
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'conftool-sync = conftool.cli.syncer:main',
            'confctl = conftool.cli.tool:main',
            'dbctl = conftool.extensions.dbconfig:main [with_dbctl]'
        ],
    },
    extras_require={
        'with_dbctl': [],  # No extra dependencies, but allow to mark it
    },
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: System :: Clustering',
    ],
)

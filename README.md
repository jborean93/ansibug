# Ansibug

[![Test workflow](https://github.com/jborean93/ansibug/actions/workflows/ci.yml/badge.svg)](https://github.com/jborean93/ansibug/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/jborean93/ansibug/graph/badge.svg?token=JHxSi6T0JJ)](https://codecov.io/gh/jborean93/ansibug)
[![PyPI version](https://badge.fury.io/py/ansibug.svg)](https://badge.fury.io/py/ansibug)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jborean93/ansibug/blob/main/LICENSE)

The core component of the Ansible Debug Adapter Protocol used for debugging Ansible playbooks.
See more documentation for `ansibug` at https://jborean93.github.io/ansibug/.

Please note this library should be considered a preview.
New features and behaviour changes should be expected during this preview period.

# Debug Adapter
This library combined with a [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/) client, like Visual Studio Code, can be used to run and debug Ansible playbook's interactively.
It supports basic features like stepping in, over, and out of tasks in a play with support for getting and setting variables at runtime.

![ansible_example](https://jborean93.github.io/ansibug/images/ansibug_example.gif)

More information about the debug adapter and debugging experience of Ansible can be found under [the docs](https://jborean93.github.io/ansibug/).

# Requirements
The following Python requirements must be met before using this library:

+ Python 3.9+ (dependent on `ansible-core` support)
+ `ansible-core >= 2.14.0`
+ Linux or macOS (no Windows)

The debugger aims to continue to support the current `ansible-core` versions that have no reached End Of Life.
See the [ansible-core support matrix](https://docs.ansible.com/ansible/devel/reference_appendices/release_and_maintenance.html#ansible-core-support-matrix) to see the current versions and the control node python versions for those versions.
There are no guarantees that all features will be supported across Ansible versions, new features might be reliant on changes only present in newer Ansible versions.
Any such features will be explicitly called out in the documentation.

# Installation
This library has been published on PyPI and can be installed with:

```bash
python -m pip install ansibug
```

To test out the changes locally run the following:
```bash
git clone https://github.com/jborean93/ansibug.git

python -m pip install -e .[dev]
pre-commit install
```

This will install the current code in editable mode and also include some development libraries needed for testing or other development features.

# Testing
This library uses [tox](https://tox.wiki/) to run the sanity and integration tests.
Once the dev extras for this library has been installed, all the tests can be run by running the `tox` command.

As the support matrix for this library can take some time to run it might be beneficial to run only certain tests.
The following factors are available in tox

+ `sanity`
+ `py3{9,10,11,12}`
+ `ansible_{2.14,2.15,2.16,2.17,devel}`

Here are some example factors that can be invoked with tox:

```bash
# Run only the sanity tests
tox run -f sanity

# Run Ansible 2.16 on all its supported Python versions
tox run -f ansible_2.16

# Run Python 3.12 on all the supported Ansible versions
tox run -f py312

# Run Ansible 2.16 tests on Python 3.12
tox run -f py312 ansible_2.16
```
